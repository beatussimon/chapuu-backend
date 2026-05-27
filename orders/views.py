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
from config.pagination import StandardPagination

logger = logging.getLogger(__name__)

class OrderViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing orders.
    Customers can place orders and view their history.
    Sellers can manage orders for their store.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('no_pagination', 'false') == 'true':
            return None
        return super().paginate_queryset(queryset)


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
            return qs.order_by('created_at')

        # Authenticated Queryset
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            queryset = Order.objects.select_related('review').all()
        elif user.role == 'SELLER':
            queryset = Order.objects.select_related('review').filter(store__owner=user)
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY']:
            store = user.employed_store
            if not store:
                from stores.models import Store
                store = Store.objects.first()
            if store:
                queryset = Order.objects.select_related('review').filter(store=store)
            else:
                queryset = Order.objects.none()
        else:
            queryset = Order.objects.select_related('review').filter(customer=user)

        if store_id:
            queryset = queryset.filter(store_id=store_id)

        search = self.request.query_params.get('search')
        if search:
            from django.db.models import Q
            query = Q(store__name__icontains=search) | Q(customer__username__icontains=search) | Q(customer__first_name__icontains=search) | Q(customer__last_name__icontains=search)
            if search.isdigit():
                query |= Q(id=int(search))
            queryset = queryset.filter(query)

        is_locked = self.request.query_params.get('is_locked')
        if is_locked in ['true', 'True', '1']:
            from django.db.models import Q
            queryset = queryset.filter(Q(is_locked=True) | Q(delivery_code_attempts__gt=0))

        exclude_inactive = self.request.query_params.get('exclude_inactive')
        if exclude_inactive in ['true', 'True', '1']:
            queryset = queryset.exclude(state__in=[
                Order.State.COMPLETED,
                Order.State.CANCELLED,
                Order.State.REFUNDED,
                Order.State.EXPIRED
            ])
            
        return queryset.order_by('-created_at')


    def perform_create(self, serializer):
        user = self.request.user
        is_instant = serializer.validated_data.get('is_instant_payment', False)

        # Only staff can mark an order as instant payment
        STAFF_ROLES = ['SELLER', 'ADMIN', 'SUPERUSER', 'ACCOUNTANT', 'CHEF']
        if is_instant and user.role not in STAFF_ROLES and not user.is_superuser:
            raise PermissionDenied("Only store staff can place instant payment (walk-in) orders.")

        order = serializer.save(customer=user if user.is_authenticated else None)

        if is_instant:
            # Payment collected in person
            Payment.objects.create(
                order=order,
                reservation=order.reservation,
                amount=order.total_amount,
                status=Payment.Status.WAIVED,
                notes=f"Walk-in instant payment collected by {user.username}."
            )
            order = OrderStateMachine.transition_order(order, Order.State.PAID, notes="Walk-in order — instant payment.", performed_by=user)
            
            # Route based on store type or auto-ready skip
            if order.state == Order.State.READY:
                pass
            elif order.store.store_type == 'SHOP':
                order = OrderStateMachine.transition_order(order, Order.State.READY, notes="Shop walk-in — instant ready.", performed_by=user)
            else:
                KitchenEngine.enqueue_order(order)
                order = OrderStateMachine.transition_order(order, Order.State.QUEUED, notes="Walk-in order queued.", performed_by=user)
        else:
            # Standard flow
            Payment.objects.create(
                order=order,
                reservation=order.reservation,
                amount=order.total_amount,
                status=Payment.Status.PENDING
            )
            order = OrderStateMachine.transition_order(order, Order.State.AWAITING_PAYMENT, notes="Awaiting offline payment.", performed_by=user)
        
        serializer.instance = order

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        order = self.get_object()
        is_admin_or_su = request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser
        if request.user != order.customer and request.user != order.store.owner and not is_admin_or_su:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        try:
            # If order is PAID, scheduled, and cancelled by customer: apply 6% cancellation fee
            if order.state == Order.State.PAID and order.scheduled_time is not None and request.user == order.customer:
                from decimal import Decimal
                from billing.models import CommissionLedgerEntry
                from payments.models import Refund, Payment
                from django.utils import timezone
                
                # Check if store is currently under an active free trial
                is_free_trial = False
                store = order.store
                if store.free_trial_start and store.free_trial_end:
                    is_free_trial = store.free_trial_start <= timezone.now() <= store.free_trial_end
                
                # Calculate 6% cancellation fee (waived to 0% platform share during trial)
                platform_share = Decimal('0.00') if is_free_trial else (order.total_amount * Decimal('0.03'))
                refund_amount = order.total_amount if is_free_trial else (order.total_amount * Decimal('0.94'))
                
                # Cancel the order first
                OrderStateMachine.transition_order(order, Order.State.CANCELLED, notes="Scheduled order cancelled by customer. 6% fee applied (Waived under trial)." if is_free_trial else "Scheduled order cancelled by customer. 6% fee applied.", performed_by=request.user)
                
                # Record platform's share in the commission ledger
                CommissionLedgerEntry.objects.create(
                    order=order,
                    store=store,
                    order_amount=order.total_amount,
                    commission_amount=platform_share,
                    entry_type=CommissionLedgerEntry.EntryType.CANCELLATION_FEE
                )
                
                # Record refund object in the DB for tracking
                payment = order.payments.filter(status__in=[Payment.Status.VERIFIED, Payment.Status.WAIVED]).first()
                if not payment:
                    payment = order.payments.first()
                if payment:
                    Refund.objects.create(
                        payment=payment,
                        amount=refund_amount,
                        reason="Scheduled order customer cancellation. 6% cancellation fee applied.",
                        is_successful=False
                    )
                
                return Response({"status": "Scheduled order cancelled. 6% cancellation fee applied. 94% refund recorded."})

            OrderStateMachine.transition_order(order, Order.State.CANCELLED, notes="Cancelled via API.", performed_by=request.user)
            return Response({"status": "order cancelled"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='confirm_delivery', permission_classes=[permissions.IsAuthenticated])
    def confirm_delivery(self, request, pk=None):
        order = self.get_object()
        code = request.data.get('code', '')
        
        # Verify the user is staff or delivery driver
        is_staff = request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER', 'DELIVERY', 'CHEF', 'ACCOUNTANT'] or request.user.is_superuser or order.store.owner == request.user
        if not is_staff:
            return Response({"error": "Permission denied. Only staff or delivery personnel can confirm handoffs."}, status=status.HTTP_403_FORBIDDEN)

        if order.state not in [Order.State.OUT_FOR_DELIVERY, Order.State.READY]:
            return Response({"error": "Order not ready for handoff verification"}, status=status.HTTP_400_BAD_REQUEST)
            
        if order.is_locked or order.delivery_code_attempts >= 5:
            return Response({"error": "Too many failed attempts. Order is locked. Please contact store support to verify manually."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
        if not order.delivery_code or code != order.delivery_code:
            order.delivery_code_attempts += 1
            if order.delivery_code_attempts >= 5:
                order.is_locked = True
                order.is_suspicious = True
                order.save(update_fields=['delivery_code_attempts', 'is_locked', 'is_suspicious'])
                return Response({"error": "Too many failed attempts. Order is locked. Please contact store support to verify manually."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            else:
                order.save(update_fields=['delivery_code_attempts'])
                return Response({"error": f"Invalid code. {5 - order.delivery_code_attempts} attempts remaining."}, status=status.HTTP_400_BAD_REQUEST)
            
        # Transition to COMPLETED with bypass flag
        OrderStateMachine.transition_order(order, Order.State.COMPLETED, performed_by=request.user, bypass_verification=True)
        return Response({"status": "Fulfillment verified and completed"})

    @action(detail=True, methods=['post'], url_path='staff_manual_verify', permission_classes=[permissions.IsAuthenticated])
    def staff_manual_verify(self, request, pk=None):
        order = self.get_object()
        
        # Verify the user is authorized store staff or store owner
        is_authorized = request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER', 'CHEF', 'ACCOUNTANT'] or request.user.is_superuser or order.store.owner == request.user
        if not is_authorized:
            return Response({"error": "Permission denied. Only store staff can manually override and verify handoffs."}, status=status.HTTP_403_FORBIDDEN)
            
        if order.state not in [Order.State.OUT_FOR_DELIVERY, Order.State.READY]:
            return Response({"error": "Order cannot be manually verified in its current state."}, status=status.HTTP_400_BAD_REQUEST)

        # Unlock order, reset attempts, but KEEP is_suspicious flag permanently set
        order.is_locked = False
        order.delivery_code_attempts = 0
        order.is_suspicious = True
        order.save(update_fields=['is_locked', 'delivery_code_attempts', 'is_suspicious'])
        
        # Transition directly to COMPLETED (accruing the 3% platform commission naturally)
        OrderStateMachine.transition_order(
            order, 
            Order.State.COMPLETED, 
            performed_by=request.user, 
            notes=f"Manual handoff override performed by staff: {request.user.username}. Lock resolved.",
            bypass_verification=True
        )
        
        return Response({"status": "Manual fulfillment override completed. 3% commission cut logged."})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def request_reschedule(self, request, pk=None):
        order = self.get_object()
        if order.customer != request.user:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        if order.state not in [Order.State.PAID, Order.State.QUEUED] or order.scheduled_time is None:
            return Response({"error": "Only upcoming paid or queued scheduled orders can be rescheduled"}, status=status.HTTP_400_BAD_REQUEST)
            
        if getattr(order, 'reschedule_count', 0) >= 1:
            return Response({"error": "You can only reschedule this order once."}, status=status.HTTP_400_BAD_REQUEST)

        if getattr(order, 'reschedule_request_count', 0) >= 2:
            return Response({"error": "You have reached the maximum limit of reschedule requests (2)."}, status=status.HTTP_400_BAD_REQUEST)

        from django.utils import timezone
        if order.scheduled_start_time and timezone.now() > order.scheduled_start_time:
            return Response({"error": "Preparation window has already started. Rescheduling is not allowed."}, status=status.HTTP_400_BAD_REQUEST)

        new_scheduled_time = request.data.get('scheduled_time')
        if not new_scheduled_time:
            return Response({"error": "scheduled_time is required"}, status=status.HTTP_400_BAD_REQUEST)

        from django.utils.dateparse import parse_datetime
        parsed_scheduled_time = parse_datetime(new_scheduled_time) if isinstance(new_scheduled_time, str) else new_scheduled_time
        if not parsed_scheduled_time:
            return Response({"error": "Invalid scheduled_time format"}, status=status.HTTP_400_BAD_REQUEST)

        if timezone.is_naive(parsed_scheduled_time):
            parsed_scheduled_time = timezone.make_aware(parsed_scheduled_time)

        if parsed_scheduled_time <= timezone.now():
            return Response({"error": "New scheduled time must be in the future"}, status=status.HTTP_400_BAD_REQUEST)

        # Recalculate scheduled_start_time dynamically if DYNAMIC option is selected
        from datetime import timedelta
        new_start_time = None
        if order.prep_time_option == 'DYNAMIC':
            max_prep = max((item.product.get_average_prep_time() for item in order.items.all()), default=0)
            new_start_time = parsed_scheduled_time - timedelta(minutes=max_prep)
            if new_start_time <= timezone.now():
                return Response({
                    "error": f"Requested time is too close. The kitchen needs at least {max_prep} minutes to prepare this order."
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            # CUSTOM option
            custom_start = request.data.get('scheduled_start_time')
            if custom_start:
                parsed_start = parse_datetime(custom_start) if isinstance(custom_start, str) else custom_start
                if not parsed_start:
                    return Response({"error": "Invalid custom start time format"}, status=status.HTTP_400_BAD_REQUEST)
                if timezone.is_naive(parsed_start):
                    parsed_start = timezone.make_aware(parsed_start)
                if parsed_start <= timezone.now() or parsed_start >= parsed_scheduled_time:
                    return Response({"error": "Custom start time must be in the future and before the scheduled delivery/pickup time."}, status=status.HTTP_400_BAD_REQUEST)
                new_start_time = parsed_start
            else:
                # If they didn't provide scheduled_start_time for CUSTOM, keep the same diff
                if order.scheduled_start_time and order.scheduled_time:
                    diff = order.scheduled_time - order.scheduled_start_time
                    new_start_time = parsed_scheduled_time - diff
                    if timezone.is_naive(new_start_time):
                        new_start_time = timezone.make_aware(new_start_time)
                    if new_start_time <= timezone.now():
                        return Response({"error": "Rescheduled start time would be in the past. Please select a later time."}, status=status.HTTP_400_BAD_REQUEST)

        from orders.models import OrderRescheduleRequest
        # Create a new history log row
        OrderRescheduleRequest.objects.create(
            order=order,
            requested_time=parsed_scheduled_time,
            requested_start_time=new_start_time,
            status='PENDING'
        )

        order.reschedule_requested_time = parsed_scheduled_time
        order.reschedule_requested_start_time = new_start_time
        order.reschedule_status = 'PENDING'
        order.reschedule_rejection_reason = None
        order.reschedule_request_count = getattr(order, 'reschedule_request_count', 0) + 1
        order.save(update_fields=['reschedule_requested_time', 'reschedule_requested_start_time', 'reschedule_status', 'reschedule_rejection_reason', 'reschedule_request_count'])
        
        # Broadcast notice to store
        OrderStateMachine.emit_update(order)
        return Response({"status": "Reschedule request submitted", "reschedule_status": order.reschedule_status})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def respond_reschedule(self, request, pk=None):
        order = self.get_object()
        is_staff = request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER', 'CHEF'] or request.user.is_superuser or order.store.owner == request.user
        if not is_staff:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        if order.reschedule_status != 'PENDING':
            return Response({"error": "No pending reschedule request exists for this order"}, status=status.HTTP_400_BAD_REQUEST)
            
        pending_req = order.reschedule_requests.filter(status='PENDING').first()
        if not pending_req:
            return Response({"error": "No pending reschedule request log exists for this order"}, status=status.HTTP_400_BAD_REQUEST)

        approve = request.data.get('approve', False)
        if approve:
            if getattr(order, 'reschedule_count', 0) >= 1:
                return Response({"error": "This order has already been rescheduled the maximum number of times (1)."}, status=status.HTTP_400_BAD_REQUEST)
            
            pending_req.status = 'APPROVED'
            pending_req.save(update_fields=['status'])

            order.scheduled_time = pending_req.requested_time
            order.scheduled_start_time = pending_req.requested_start_time
            order.reschedule_status = 'APPROVED'
            order.reschedule_count = getattr(order, 'reschedule_count', 0) + 1
            order.reschedule_rejection_reason = None
            order.save(update_fields=['scheduled_time', 'scheduled_start_time', 'reschedule_status', 'reschedule_count', 'reschedule_rejection_reason'])
        else:
            rejection_reason = request.data.get('rejection_reason')
            if not rejection_reason or not rejection_reason.strip():
                return Response({"error": "A rejection reason is required when rejecting a reschedule request."}, status=status.HTTP_400_BAD_REQUEST)
            
            pending_req.status = 'REJECTED'
            pending_req.rejection_reason = rejection_reason.strip()
            pending_req.save(update_fields=['status', 'rejection_reason'])

            order.reschedule_status = 'REJECTED'
            order.reschedule_rejection_reason = rejection_reason.strip()
            order.save(update_fields=['reschedule_status', 'reschedule_rejection_reason'])
            
        OrderStateMachine.emit_update(order)
        return Response({"status": f"Reschedule request {'approved' if approve else 'rejected'}", "reschedule_status": order.reschedule_status})

    @action(detail=True, methods=['post'], url_path='admin_reset_lock', permission_classes=[permissions.IsAuthenticated])
    def admin_reset_lock(self, request, pk=None):
        order = self.get_object()
        if request.user.role not in ['ADMIN', 'SUPERUSER'] and not request.user.is_superuser:
            return Response({"error": "Permission denied. Only platform administrators can reset locks."}, status=status.HTTP_403_FORBIDDEN)
        order.is_locked = False
        order.delivery_code_attempts = 0
        order.save(update_fields=['is_locked', 'delivery_code_attempts'])
        OrderStateMachine.emit_update(order)
        return Response({"status": "Order unlocked and verification attempts reset."})

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>\d+)/ready', permission_classes=[permissions.IsAuthenticated])
    def mark_item_ready(self, request, pk=None, item_id=None):
        order = self.get_object()
        if request.user.role not in ['SELLER', 'ADMIN', 'SUPERUSER', 'CHEF'] and not request.user.is_superuser:
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

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def reverse_geocode(self, request):
        lat_raw = request.query_params.get('lat')
        lon_raw = request.query_params.get('lon')
        if not lat_raw or not lon_raw:
            return Response({"error": "lat and lon are required parameters"}, status=status.HTTP_400_BAD_REQUEST)
        
        from django.core.cache import cache
        import requests
        from decimal import Decimal

        try:
            # Round to 4 decimal places (~11m precision) to maximize cache hits for users in same spot
            lat = str(Decimal(lat_raw).quantize(Decimal('0.0001')))
            lon = str(Decimal(lon_raw).quantize(Decimal('0.0001')))
            
            cache_key = f"reverse_geo_{lat}_{lon}"
            cached_address = cache.get(cache_key)
            if cached_address:
                return Response({"display_name": cached_address, "cached": True})

            headers = {
                'User-Agent': 'Chapuu-Backend-Reverse-Geocoding-Proxy/1.0 (contact: support@chapuu.com)'
            }
            response = requests.get(
                f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json",
                headers=headers,
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'display_name' in data:
                    display_name = data['display_name']
                    # Cache for 7 days - geodata doesn't change often
                    cache.set(cache_key, display_name, 60*60*24*7)
                    return Response({"display_name": display_name, "cached": False})
            
            # If throttled (429) or service down, fallback to raw coordinates
            return Response({"display_name": f"Location: {lat_raw}, {lon_raw}", "fallback": True})
            
        except Exception as e:
            return Response({"display_name": f"Location: {lat_raw}, {lon_raw}", "fallback": True, "error": str(e)})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def renegotiate_delivery_fee(self, request, pk=None):
        order = self.get_object()
        if order.customer != request.user:
            return Response({"error": "Permission denied. Only the customer can request renegotiation of delivery fee."}, status=status.HTTP_403_FORBIDDEN)
        order.delivery_fee_status = 'RENEGOTIATE'
        order.save(update_fields=['delivery_fee_status'])
        OrderStateMachine.emit_update(order)
        return Response({"status": "Renegotiation request submitted.", "delivery_fee_status": order.delivery_fee_status})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def update_delivery_fee(self, request, pk=None):
        order = self.get_object()
        is_staff = request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER', 'ACCOUNTANT'] or request.user.is_superuser or order.store.owner == request.user
        if not is_staff:
            return Response({"error": "Permission denied. Only store staff can update the delivery fee."}, status=status.HTTP_403_FORBIDDEN)
        
        new_fee_val = request.data.get('delivery_fee')
        if new_fee_val is None:
            return Response({"error": "delivery_fee is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        from decimal import Decimal
        try:
            new_fee = Decimal(str(new_fee_val))
        except (ValueError, TypeError):
            return Response({"error": "Invalid delivery_fee value"}, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            order.delivery_fee = new_fee
            items_subtotal = sum(item.unit_price * item.quantity for item in order.items.all())
            order.total_amount = items_subtotal + new_fee
            order.delivery_fee_status = 'AGREED'
            order.save(update_fields=['delivery_fee', 'total_amount', 'delivery_fee_status'])
            OrderStateMachine.emit_update(order)
            
        return Response({
            "status": "Delivery fee updated", 
            "delivery_fee": order.delivery_fee, 
            "total_amount": order.total_amount,
            "delivery_fee_status": order.delivery_fee_status
        })

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def advance_state(self, request, pk=None):
        order = self.get_object()
        user = request.user
        new_state = request.data.get('state')
        
        allowed = (user.role in ['ADMIN', 'SUPERUSER', 'SELLER'] or user.is_superuser)
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
            if new_state == Order.State.PAID:
                if 'delivery_fee' in request.data:
                    from decimal import Decimal
                    order.delivery_fee = Decimal(str(request.data.get('delivery_fee') or 0))
                    items_subtotal = sum(item.unit_price * item.quantity for item in order.items.all())
                    order.total_amount = items_subtotal + order.delivery_fee
                    order.delivery_fee_status = 'AGREED'
                    order.save(update_fields=['delivery_fee', 'total_amount', 'delivery_fee_status'])

            updated_order = OrderStateMachine.transition_order(order, new_state, notes="Manual advance.", performed_by=user)
            
            if new_state == Order.State.PAID:
                # Explicitly verify payments
                from payments.models import Payment
                updated_order.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.VERIFIED)
                
                # Explicitly confirm linked reservation
                if updated_order.fulfillment_mode == Order.FulfillmentMode.RESERVATION and updated_order.reservation:
                    updated_order.reservation.status = 'CONFIRMED'
                    updated_order.reservation.save(update_fields=['status'])

            if new_state in [Order.State.PAID, Order.State.QUEUED]:
                if updated_order.state == Order.State.READY:
                    pass
                elif updated_order.store.store_type == 'SHOP':
                    if updated_order.state == Order.State.PAID:
                        updated_order = OrderStateMachine.transition_order(updated_order, Order.State.READY, notes="Shop kitchen skip.", performed_by=user)
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

                    if new_state == Order.State.PAID:
                        if locked_order.customer:
                            from django.db.models import F
                            locked_order.customer.__class__.objects.filter(pk=locked_order.customer_id).update(
                                loyalty_points=F('loyalty_points') + int(locked_order.total_amount)
                            )
                        # Explicitly verify payments
                        from payments.models import Payment
                        locked_order.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.VERIFIED)
                        
                        # Explicitly confirm linked reservation
                        if locked_order.fulfillment_mode == Order.FulfillmentMode.RESERVATION and locked_order.reservation:
                            locked_order.reservation.status = 'CONFIRMED'
                            locked_order.reservation.save(update_fields=['status'])

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
