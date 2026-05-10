from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from orders.models import Order, OrderItem, OrderEventLog
from orders.serializers import OrderSerializer, PublicOrderSerializer
from orders.services import OrderStateMachine
from payments.models import Payment
from stores.services import KitchenEngine
from django.core.exceptions import PermissionDenied
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

    def get_serializer_class(self):
        # Use a restricted serializer for anonymous users (Public TV displays)
        if not self.request.user or not self.request.user.is_authenticated:
            return PublicOrderSerializer
        return OrderSerializer

    def get_queryset(self):
        user = self.request.user
        store_id = self.request.query_params.get('store', None)
        
        # Public Queryset (Used by TV displays)
        if not user or not user.is_authenticated:
            # Only return orders that make sense to show in public (paid and above)
            qs = Order.objects.filter(state__in=[
                Order.State.PAID, 
                Order.State.QUEUED, 
                Order.State.PREPARING, 
                Order.State.READY
            ])
            if store_id:
                qs = qs.filter(store_id=store_id)
            return qs

        # Authenticated Queryset
        if store_id:
            return Order.objects.filter(store_id=store_id)

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
        user = self.request.user
        is_instant = serializer.validated_data.get('is_instant_payment', False)

        # Only staff can mark an order as instant payment
        STAFF_ROLES = ['SELLER', 'ADMIN', 'ACCOUNTANT', 'CHEF']
        if is_instant and user.role not in STAFF_ROLES:
            raise PermissionDenied("Only store staff can place instant payment (walk-in) orders.")

        order = serializer.save(customer=user if user.is_authenticated else None)

        if is_instant:
            # Payment collected in person
            Payment.objects.create(
                order=order,
                amount=order.total_amount,
                status=Payment.Status.WAIVED,
                notes=f"Walk-in instant payment collected by {user.username}."
            )
            order = OrderStateMachine.transition_order(order, Order.State.PAID, notes="Walk-in order — instant payment.")
            
            # Route based on store type
            if order.store.store_type == 'SHOP':
                order = OrderStateMachine.transition_order(order, Order.State.READY, notes="Shop walk-in — instant ready.")
            else:
                KitchenEngine.enqueue_order(order)
                order = OrderStateMachine.transition_order(order, Order.State.QUEUED, notes="Walk-in order queued.")
        else:
            # Standard flow
            Payment.objects.create(
                order=order,
                amount=order.total_amount,
                status=Payment.Status.PENDING
            )
            order = OrderStateMachine.transition_order(order, Order.State.AWAITING_PAYMENT, notes="Awaiting offline payment.")
        
        serializer.instance = order

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if request.user != order.customer and request.user != order.store.owner and request.user.role != 'ADMIN':
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        try:
            OrderStateMachine.transition_order(order, Order.State.CANCELLED, notes="Cancelled via API.")
            return Response({"status": "order cancelled"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>\d+)/ready', permission_classes=[permissions.IsAuthenticated])
    def mark_item_ready(self, request, pk=None, item_id=None):
        order = self.get_object()
        if request.user.role not in ['SELLER', 'ADMIN', 'CHEF']:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        try:
            item = order.items.get(id=item_id)
            item.is_ready = True
            item.save(update_fields=['is_ready'])
            if not order.items.filter(is_ready=False).exists():
                if order.state in [Order.State.PREPARING, Order.State.QUEUED]:
                    OrderStateMachine.transition_order(order, Order.State.READY, notes="All kitchen items finished.")
            return Response({"status": "Item marked ready", "order_state": order.state})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def advance_state(self, request, pk=None):
        order = self.get_object()
        user = request.user
        new_state = request.data.get('state')
        
        allowed = (user.role in ['ADMIN', 'SELLER'])
        if not allowed:
            if user.role == 'ACCOUNTANT' and new_state in [Order.State.PAID, Order.State.CANCELLED]: allowed = True
            elif user.role == 'CHEF' and new_state in [Order.State.PREPARING, Order.State.READY]: allowed = True
            elif user.role == 'DELIVERY' and new_state in [Order.State.OUT_FOR_DELIVERY, Order.State.COMPLETED]: allowed = True
            
        if not allowed:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        if order.state == Order.State.PAID and new_state == Order.State.CANCELLED:
            from django.utils import timezone
            from datetime import timedelta
            if timezone.now() - order.created_at > timedelta(minutes=10):
                return Response({"error": "Cannot cancel a paid order after 10 mins."}, status=400)

        try:
            if new_state == Order.State.PAID and 'delivery_fee' in request.data:
                order.delivery_fee = request.data.get('delivery_fee')
                order.total_amount = float(order.total_amount) + float(order.delivery_fee)
                order.save(update_fields=['delivery_fee', 'total_amount'])

            updated_order = OrderStateMachine.transition_order(order, new_state, notes="Manual advance.")
            
            if new_state in [Order.State.PAID, Order.State.QUEUED]:
                if updated_order.store.store_type == 'SHOP':
                    if updated_order.state == Order.State.PAID:
                        updated_order = OrderStateMachine.transition_order(updated_order, Order.State.READY, notes="Shop kitchen skip.")
                else:
                    KitchenEngine.enqueue_order(updated_order)
                
            return Response({"status": "State advanced", "order_state": updated_order.state})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def bulk_advance_state(self, request):
        order_ids = request.data.get('order_ids', [])
        new_state = request.data.get('state')
        if not order_ids or not new_state:
            return Response({"error": "Missing order_ids or state"}, status=400)

        processed_ids = []
        errors = []
        store_id = None

        for oid in order_ids:
            try:
                order = Order.objects.get(pk=oid)
                if order.state == new_state:
                    processed_ids.append(oid)
                    continue
                if not store_id: store_id = order.store_id

                with transaction.atomic():
                    locked_order = Order.objects.select_for_update().get(id=order.id)
                    current_state = locked_order.state
                    if new_state not in OrderStateMachine.VALID_TRANSITIONS.get(current_state, []):
                        errors.append(f"Order #{oid}: Invalid transition from {current_state}")
                        continue
                    
                    locked_order.state = new_state
                    locked_order.save(update_fields=['state', 'updated_at'])

                    if new_state == Order.State.PAID and locked_order.customer:
                        from django.db.models import F
                        locked_order.customer.__class__.objects.filter(pk=locked_order.customer_id).update(
                            loyalty_points=F('loyalty_points') + int(locked_order.total_amount)
                        )

                    OrderEventLog.objects.create(order=locked_order, previous_state=current_state, new_state=new_state, notes="Bulk API advance")

                    if new_state in [Order.State.PAID, Order.State.QUEUED]:
                        if locked_order.store.store_type == 'SHOP':
                            if locked_order.state == Order.State.PAID:
                                locked_order.state = Order.State.READY
                                locked_order.save(update_fields=['state', 'updated_at'])
                        else:
                            KitchenEngine.enqueue_order(locked_order)

                processed_ids.append(oid)
            except Exception as e:
                errors.append(f"Order #{oid}: {str(e)}")

        if processed_ids and store_id:
            OrderStateMachine.emit_bulk_update(processed_ids, new_state, store_id)

        return Response({
            "status": "Bulk processing complete",
            "processed_count": len(processed_ids),
            "processed_ids": processed_ids,
            "errors": errors
        }, status=status.HTTP_200_OK if not errors else 207)
