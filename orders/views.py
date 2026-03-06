from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from orders.models import Order
from orders.serializers import OrderSerializer
from orders.services import OrderStateMachine

class OrderViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing orders.
    Customers can place orders and view their history.
    Sellers can manage orders for their store.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'SELLER':
            return Order.objects.filter(store__owner=user)
        elif user.role == 'ADMIN':
            return Order.objects.all()
        else:
            return Order.objects.filter(customer=user)

    def perform_create(self, serializer):
        # Auto-assign customer if not provided in payload
        order = serializer.save(customer=self.request.user)
        # Immediately kick it into payment holding state
        OrderStateMachine.transition_order(order, Order.State.AWAITING_PAYMENT, notes="Order created. Awaiting payment.")

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        order = self.get_object()
        
        # Only customer or store owner can cancel
        if request.user != order.customer and request.user != order.store.owner:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            OrderStateMachine.transition_order(order, Order.State.CANCELLED, notes="Cancelled via API req.")
            return Response({"status": "order cancelled"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='items/(?P<item_id>\d+)/ready', permission_classes=[permissions.IsAuthenticated])
    def mark_item_ready(self, request, pk=None, item_id=None):
        order = self.get_object()
        
        if request.user.role != 'SELLER' and request.user.role != 'ADMIN':
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

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def advance_state(self, request, pk=None):
        order = self.get_object()
        if request.user.role != 'SELLER' and request.user.role != 'ADMIN':
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        new_state = request.data.get('state')
        try:
            OrderStateMachine.transition_order(order, new_state, notes="Manual state advance via KDS")
            
            # For SHOP stores: when payment is verified (PAID), skip kitchen → go straight to READY
            if new_state in [Order.State.PAID, Order.State.QUEUED]:
                is_shop = order.store.store_type == 'SHOP'
                if is_shop:
                    # Shop orders skip kitchen entirely: PAID → READY
                    if order.state == Order.State.PAID:
                        OrderStateMachine.transition_order(order, Order.State.READY, notes="Shop order — kitchen skipped.")
                else:
                    # Restaurant orders go through kitchen
                    from stores.services import KitchenEngine
                    KitchenEngine.enqueue_order(order)
                
            return Response({"status": "State advanced", "order_state": order.state})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

