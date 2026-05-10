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
        from payments.models import Payment
        from stores.services import KitchenEngine
        from django.core.exceptions import PermissionDenied

        user = self.request.user
        is_instant = serializer.validated_data.get('is_instant_payment', False)

        # Only staff can mark an order as instant payment
        STAFF_ROLES = ['SELLER', 'ADMIN', 'ACCOUNTANT', 'CHEF']
        if is_instant and user.role not in STAFF_ROLES:
            raise PermissionDenied("Only store staff can place instant payment (walk-in) orders.")

        order = serializer.save(customer=user if user.is_authenticated else None)

        if is_instant:
            # ── WALK-IN / PAY-ON-SPOT FLOW ──────────────────────────────────
            # Payment was collected in person. Skip AWAITING_PAYMENT entirely.
            Payment.objects.create(
                order=order,
                amount=order.total_amount,
                status=Payment.Status.WAIVED,
                notes=f"Walk-in instant payment collected in person by {user.username}."
            )
            # Transition directly: CREATED → PAID
            order = OrderStateMachine.transition_order(
                order, Order.State.PAID,
                notes=f"Walk-in order — instant payment collected by {user.username}."
            )
            # Route to kitchen or mark ready based on store type
            is_shop = order.store.store_type == 'SHOP'
            if is_shop:
                # Shops skip kitchen: PAID → READY
                order = OrderStateMachine.transition_order(
                    order, Order.State.READY,
                    notes="Shop walk-in — instant ready for pickup."
                )
            else:
                # Restaurants: enqueue to kitchen
                KitchenEngine.enqueue_order(order)
                # Optionally auto-transition to QUEUED so kitchen sees it
                order = OrderStateMachine.transition_order(
                    order, Order.State.QUEUED,
                    notes="Walk-in order queued to kitchen."
                )
        else:
            # ── STANDARD OFFLINE PAYMENT FLOW ───────────────────────────────
            # Customer will pay offline (M-Pesa, bank transfer, cash deposit)
            # and upload proof. Accountant verifies.
            Payment.objects.create(
                order=order,
                amount=order.total_amount,
                status=Payment.Status.PENDING
            )
            order = OrderStateMachine.transition_order(
                order, Order.State.AWAITING_PAYMENT,
                notes="Order placed. Awaiting offline payment."
            )
        
        # Sync the serializer instance with the latest state
        serializer.instance = order

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

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>\d+)/ready', permission_classes=[permissions.IsAuthenticated])
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
            
        # Walk-in paid orders can only be cancelled within 10 minutes of creation
        if order.state == Order.State.PAID and new_state == Order.State.CANCELLED:
            from django.utils import timezone
            from datetime import timedelta
            grace_period = timedelta(minutes=10)
            if timezone.now() - order.created_at > grace_period:
                return Response(
                    {"error": "Cannot cancel a paid order after 10 minutes. Process a refund instead."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Also update the payment record to FAILED when cancelling
            try:
                payment = order.payments.filter(status__in=['PENDING', 'WAIVED']).first()
                if payment:
                    payment.status = Payment.Status.FAILED
                    payment.notes = (payment.notes or '') + f"\nCancelled by {request.user.username}."
                    payment.save(update_fields=['status', 'notes', 'updated_at'])
            except Exception:
                pass  # Don't block cancellation if payment update fails

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

    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def bulk_advance_state(self, request):
        order_ids = request.data.get('order_ids', [])
        new_state = request.data.get('state')
        user = request.user
        
        if not order_ids or not new_state:
            return Response({"error": "order_ids and state are required"}, status=status.HTTP_400_BAD_REQUEST)

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

        processed_ids = []
        errors = []
        store_id = None

        for oid in order_ids:
            try:
                order = Order.objects.get(pk=oid)
                
                # IDEMPOTENCY: Skip if already in the target state
                if order.state == new_state:
                    processed_ids.append(oid)
                    continue

                if not store_id:
                    store_id = order.store_id

                # Transition logic
                with transaction.atomic():
                    locked_order = Order.objects.select_for_update().get(id=order.id)
                    current_state = locked_order.state
                    
                    if new_state not in OrderStateMachine.VALID_TRANSITIONS.get(current_state, []):
                        errors.append(f"Order #{oid}: Invalid transition from {current_state} to {new_state}")
                        continue
                    
                    locked_order.state = new_state
                    locked_order.save(update_fields=['state', 'updated_at'])

                    if new_state == Order.State.PAID and locked_order.customer:
                        from django.db.models import F
                        locked_order.customer.__class__.objects.filter(pk=locked_order.customer_id).update(
                            loyalty_points=F('loyalty_points') + int(locked_order.total_amount)
                        )

                    OrderEventLog.objects.create(
                        order=locked_order,
                        previous_state=current_state,
                        new_state=new_state,
                        notes="Bulk state advance via API"
                    )

                    if new_state in [Order.State.PAID, Order.State.QUEUED]:
                        if locked_order.store.store_type == 'SHOP':
                            if locked_order.state == Order.State.PAID:
                                locked_order.state = Order.State.READY
                                locked_order.save(update_fields=['state', 'updated_at'])
                        else:
                            from stores.services import KitchenEngine
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
        }, status=status.HTTP_200_OK if not errors else status.HTTP_207_MULTI_STATUS)

