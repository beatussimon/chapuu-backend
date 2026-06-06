from django.db import transaction
from django.core.exceptions import ValidationError
from orders.models import Order, OrderEventLog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import json

class OrderStateMachine:
    VALID_TRANSITIONS = {
        Order.State.CREATED: [Order.State.AWAITING_PAYMENT, Order.State.CANCELLED, Order.State.PAID, Order.State.EXPIRED],
        Order.State.AWAITING_PAYMENT: [Order.State.PAID, Order.State.CANCELLED, Order.State.EXPIRED],
        Order.State.PAID: [
            Order.State.QUEUED,
            Order.State.PREPARING,
            Order.State.READY,
            Order.State.REFUNDED,
            Order.State.CANCELLED,   # Walk-in orders can be cancelled within 10 minutes of creation
        ],
        Order.State.QUEUED: [Order.State.PREPARING, Order.State.CANCELLED, Order.State.REFUNDED],
        Order.State.PREPARING: [Order.State.READY, Order.State.CANCELLED, Order.State.REFUNDED],
        Order.State.READY: [Order.State.OUT_FOR_DELIVERY, Order.State.COMPLETED, Order.State.REFUNDED],
        Order.State.OUT_FOR_DELIVERY: [Order.State.COMPLETED, Order.State.REFUNDED],
        Order.State.COMPLETED: [],  # Strict block: completed orders are non-refundable and final
        Order.State.CANCELLED: [],
        Order.State.EXPIRED: [],
        Order.State.REFUNDED: [],
    }

    @classmethod
    def transition_order(cls, order: Order, new_state: str, notes: str = "", performed_by=None, bypass_verification: bool = False) -> Order:
        """
        Transitions the order to a new state atomically, logging the event.
        Validates whether the transition is allowed.
        """
        current_state = order.state
        
        # IDEMPOTENCY: If already in target state, just return success
        if current_state == new_state:
            return order

        valid_targets = cls.VALID_TRANSITIONS.get(current_state, [])
        
        if new_state not in valid_targets:
            raise ValidationError(f"Invalid transition from {current_state} to {new_state}.")

        # Block direct completions for verification-bound orders unless verification bypassed
        if new_state == Order.State.COMPLETED and not bypass_verification:
            if order.fulfillment_mode in [Order.FulfillmentMode.DELIVERY, Order.FulfillmentMode.PICKUP, Order.FulfillmentMode.TAKEAWAY] and not order.is_instant_payment:
                raise ValidationError("Handoff verification code required to complete this order.")

        with transaction.atomic():
            locked_order = Order.objects.select_for_update().get(id=order.id)
            
            if new_state not in cls.VALID_TRANSITIONS.get(locked_order.state, []):
                raise ValidationError(f"Invalid transition from {locked_order.state} to {new_state}.")
            
            previous_state = locked_order.state
            locked_order.state = new_state
            
            if new_state == Order.State.PAID:
                if locked_order.customer:
                    from django.db.models import F
                    locked_order.customer.__class__.objects.filter(pk=locked_order.customer_id).update(
                        loyalty_points=F('loyalty_points') + int(locked_order.total_amount)
                    )
                
                if locked_order.store.store_type == 'SHOP':
                    # Shop workflow: skip kitchen queue, land directly in PREPARING
                    locked_order.state = Order.State.PREPARING
                    new_state = Order.State.PREPARING
                else:
                    # Restaurant workflow: Auto-ready non-kitchen items
                    locked_order.items.filter(product__requires_kitchen=False).update(is_ready=True)
                    
                    # If there are no items requiring kitchen prep, transition state directly to READY
                    has_kitchen_items = locked_order.items.filter(product__requires_kitchen=True).exists()
                    if not has_kitchen_items:
                        locked_order.state = Order.State.READY
                        new_state = Order.State.READY

            update_fields = ['state', 'updated_at']

            # Generate handoff code when entering delivery/ready states for target modes
            should_generate_code = False
            if new_state == Order.State.OUT_FOR_DELIVERY and locked_order.fulfillment_mode == Order.FulfillmentMode.DELIVERY:
                should_generate_code = True
            elif new_state == Order.State.READY and locked_order.fulfillment_mode in [Order.FulfillmentMode.PICKUP, Order.FulfillmentMode.TAKEAWAY]:
                should_generate_code = True

            if should_generate_code:
                if not locked_order.delivery_code:
                    import secrets
                    locked_order.delivery_code = ''.join(secrets.choice('0123456789') for _ in range(6))
                    locked_order.delivery_code_attempts = 0
                    update_fields.extend(['delivery_code', 'delivery_code_attempts'])

            locked_order.save(update_fields=update_fields)

            if new_state in [Order.State.CANCELLED, Order.State.EXPIRED, Order.State.REFUNDED] and previous_state not in [Order.State.CANCELLED, Order.State.EXPIRED, Order.State.REFUNDED]:
                # Restores locked stock levels dynamically
                from catalog.models import InventoryStock
                for item in locked_order.items.select_related('product').all():
                    product = item.product
                    if product.requires_inventory:
                        try:
                            stock = InventoryStock.objects.select_for_update().get(product=product)
                            stock.quantity += item.quantity
                            stock.save(update_fields=['quantity'])
                        except InventoryStock.DoesNotExist:
                            pass
                    if product.requires_kitchen:
                        for recipe_item in product.recipe_ingredients.select_related('ingredient').all():
                            try:
                                stock = InventoryStock.objects.select_for_update().get(ingredient=recipe_item.ingredient)
                                stock.quantity += recipe_item.quantity_required * item.quantity
                                stock.save(update_fields=['quantity'])
                            except InventoryStock.DoesNotExist:
                                pass



            # Accrue platform commission on order completion (Waived to 0.00 during Free Trial)
            if new_state == Order.State.COMPLETED:
                from billing.models import CommissionLedgerEntry
                from decimal import Decimal
                from django.utils import timezone
                
                is_free_trial = False
                store = locked_order.store
                if store.free_trial_start and store.free_trial_end:
                    is_free_trial = store.free_trial_start <= timezone.now() <= store.free_trial_end
                    
                # Dynamic commission rate: 7% for RESTAURANT, 2% for SHOP
                rate = Decimal('0.07') if store.store_type == 'RESTAURANT' else Decimal('0.02')
                
                # Waive platform commission (0%) for walk-in POS orders (instant payments)
                if locked_order.is_instant_payment:
                    rate = Decimal('0.00')
                    
                commission_amount = Decimal('0.00') if is_free_trial else (locked_order.total_amount * rate)
                
                CommissionLedgerEntry.objects.create(
                    order=locked_order,
                    store=store,
                    order_amount=locked_order.total_amount,
                    commission_rate=rate * 100,
                    commission_amount=commission_amount,
                    entry_type=CommissionLedgerEntry.EntryType.COMMISSION
                )

            OrderEventLog.objects.create(
                order=locked_order,
                previous_state=previous_state,
                new_state=new_state,
                notes=notes,
                performed_by=performed_by
            )

        # Emit WebSocket event after successful DB transaction
        cls.emit_update(locked_order)
        return locked_order

    @classmethod
    def emit_update(cls, order: Order):
        try:
            channel_layer = get_channel_layer()
            if not channel_layer:
                return

            payload = {
                'order_id': order.id,
                'state': order.state,
                'store_id': order.store_id
            }

            # Broadcast to store-specific group
            async_to_sync(channel_layer.group_send)(
                f'store_{order.store_id}_orders',
                {
                    'type': 'order_update',
                    'message': payload
                }
            )
            
            # Broadcast to global group
            async_to_sync(channel_layer.group_send)(
                'global_orders',
                {
                    'type': 'order_update',
                    'message': payload
                }
            )
            # Broadcast to per-order group
            async_to_sync(channel_layer.group_send)(
                f'order_{order.id}',
                {
                    'type': 'order_update',
                    'message': payload
                }
            )
        except Exception as e:
            # Real-time failures should never crash the main transaction
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Real-time broadcast failed for Order #{order.id}: {str(e)}")

        # Send push notification for significant state changes to the customer
        if order.customer_id and order.state in [Order.State.PREPARING, Order.State.READY, Order.State.OUT_FOR_DELIVERY]:
            try:
                from users.models import PushDevice
                import requests
                
                devices = PushDevice.objects.filter(user_id=order.customer_id)
                if devices.exists():
                    messages = []
                    
                    title = f"Order Update: {order.store.name}"
                    body = f"Your order is now {order.get_state_display()}."
                    
                    for device in devices:
                        messages.append({
                            'to': device.push_token,
                            'sound': 'default',
                            'title': title,
                            'body': body,
                            'data': {'orderId': order.id, 'state': order.state},
                        })
                    
                    response = requests.post(
                        'https://exp.host/--/api/v2/push/send',
                        headers={
                            'Accept': 'application/json',
                            'Accept-encoding': 'gzip, deflate',
                            'Content-Type': 'application/json',
                        },
                        json=messages,
                        timeout=5
                    )
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to send push notification for Order #{order.id}: {str(e)}")

    @classmethod
    def emit_bulk_update(cls, order_ids: list, new_state: str, store_id: int):
        try:
            channel_layer = get_channel_layer()
            if not channel_layer:
                return

            payload = {
                'order_ids': order_ids,
                'state': new_state,
                'store_id': store_id,
                'is_bulk': True
            }

            # Broadcast to store-specific group
            async_to_sync(channel_layer.group_send)(
                f'store_{store_id}_orders',
                {
                    'type': 'order_update',
                    'message': payload
                }
            )
            
            # Broadcast to global group
            async_to_sync(channel_layer.group_send)(
                'global_orders',
                {
                    'type': 'order_update',
                    'message': payload
                }
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Bulk real-time broadcast failed for Store #{store_id}: {str(e)}")
