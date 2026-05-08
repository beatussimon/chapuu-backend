from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from orders.models import Order
from orders.serializers import OrderSerializer
from orders.services import OrderStateMachine
import logging

logger = logging.getLogger(__name__)

class OrderViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing orders.
    Customers can place orders and view their history.
    Sellers can manage orders for their store.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        store_id = self.request.query_params.get('store', None)
        
        # If a specific store is requested (Public TV Display mode)
        if store_id:
            qs = Order.objects.filter(store_id=store_id)
            if not user or not user.is_authenticated:
                # Return only non-PII fields for anonymous TV displays
                return qs.only('id', 'state', 'fulfillment_mode', 'created_at')
            return qs

        # Safety check for anonymous users
        if not user or not user.is_authenticated:
            return Order.objects.none()

        if user.role == 'ADMIN':
            return Order.objects.select_related('review').all()
        elif user.role == 'SELLER':
            return Order.objects.select_related('review').filter(store__owner=user)
        elif user.role in ['CHEF', 'ACCOUNTANT']:
            if user.employed_store:
                return Order.objects.select_related('review').filter(store=user.employed_store)
            return Order.objects.select_related('review').all()
        elif user.role == 'DELIVERY':
            qs = Order.objects.select_related('review').filter(fulfillment_mode='DELIVERY')
            if user.employed_store:
                qs = qs.filter(store=user.employed_store)
            return qs
        else:
            return Order.objects.select_related('review').filter(customer=user)

    def perform_create(self, serializer):
        # Auto-assign customer if not provided in payload
        order = serializer.save(customer=self.request.user)
        # Immediately kick it into payment holding state
        OrderStateMachine.transition_order(order, Order.State.AWAITING_PAYMENT, notes="Order created. Awaiting payment.")

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        order = self.get_object()
        
        # Only customer or store owner can cancel
        if request.user != order.customer and request.user != order.store.owner and request.user.role != 'ADMIN':
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            OrderStateMachine.transition_order(order, Order.State.CANCELLED, notes="Cancelled via API req.")
            return Response({"status": "order cancelled"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='items/(?P<item_id>\d+)/ready', permission_classes=[permissions.IsAuthenticated])
    def mark_item_ready(self, request, pk=None, item_id=None):
        order = self.get_object()
        
        if request.user.role not in ['SELLER', 'ADMIN', 'CHEF']:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            item = order.items.get(id=item_id)
            item.is_ready = True
            item.save(update_fields=['is_ready'])
            
            # Check if all items are ready, if so move order to READY
            if not order.items.filter(is_ready=False).exists():
                if order.state == Order.State.PREPARING or order.state == Order.State.QUEUED:
                    OrderStateMachine.transition_order(order, Order.State.READY, notes="All kitchen items finished.")
                    
            return Response({"status": "Item marked ready", "order_state": order.state})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def get_serializer_class(self):
        if self.request.query_params.get('store') and not self.request.user.is_authenticated:
            from orders.serializers import PublicOrderSerializer
            return PublicOrderSerializer
        return OrderSerializer

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def advance_state(self, request, pk=None):
        order = self.get_object()
        user = request.user
        new_state = request.data.get('state')
        
        # Role-based permission checks
        allowed = False
        if user.role == 'ADMIN' or user.role == 'SELLER':
            allowed = True
        elif user.role == 'ACCOUNTANT' and new_state in [Order.State.PAID, Order.State.CANCELLED]:
            allowed = True
        elif user.role == 'CHEF' and new_state in [Order.State.PREPARING, Order.State.READY]:
            allowed = True
        elif user.role == 'DELIVERY' and new_state in [Order.State.OUT_FOR_DELIVERY, Order.State.COMPLETED]:
            allowed = True
            
        if not allowed:
            return Response({"error": "Permission denied for this state transition"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            # Handle delivery fee if verifying payment
            if new_state == Order.State.PAID and 'delivery_fee' in request.data:
                order.delivery_fee = request.data.get('delivery_fee')
                order.total_amount = float(order.total_amount) + float(order.delivery_fee)
                order.save(update_fields=['delivery_fee', 'total_amount'])

            updated_order = OrderStateMachine.transition_order(order, new_state, notes="Manual state advance via API")
            
            # For SHOP stores: when payment is verified (PAID), skip kitchen → go straight to READY
            if new_state in [Order.State.PAID, Order.State.QUEUED]:
                is_shop = updated_order.store.store_type == 'SHOP'
                if is_shop:
                    # Shop orders skip kitchen entirely: PAID → READY
                    if updated_order.state == Order.State.PAID:
                        updated_order = OrderStateMachine.transition_order(updated_order, Order.State.READY, notes="Shop order — kitchen skipped.")
                else:
                    # Restaurant orders go through kitchen
                    from stores.services import KitchenEngine
                    KitchenEngine.enqueue_order(updated_order)
                
            return Response({"status": "State advanced", "order_state": updated_order.state})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

