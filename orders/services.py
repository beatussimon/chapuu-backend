from django.db import transaction
from django.core.exceptions import ValidationError
from orders.models import Order, OrderEventLog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import json

class OrderStateMachine:
    VALID_TRANSITIONS = {
        Order.State.CREATED: [Order.State.AWAITING_PAYMENT, Order.State.CANCELLED],
        Order.State.AWAITING_PAYMENT: [Order.State.PAID, Order.State.CANCELLED, Order.State.EXPIRED],
        Order.State.PAID: [Order.State.QUEUED, Order.State.PREPARING, Order.State.READY, Order.State.REFUNDED],
        Order.State.QUEUED: [Order.State.PREPARING, Order.State.CANCELLED, Order.State.REFUNDED],
        Order.State.PREPARING: [Order.State.READY, Order.State.CANCELLED, Order.State.REFUNDED],
        Order.State.READY: [Order.State.OUT_FOR_DELIVERY, Order.State.COMPLETED, Order.State.REFUNDED],
        Order.State.OUT_FOR_DELIVERY: [Order.State.COMPLETED, Order.State.REFUNDED],
        Order.State.COMPLETED: [Order.State.REFUNDED],
        Order.State.CANCELLED: [],
        Order.State.EXPIRED: [],
        Order.State.REFUNDED: [],
    }

    @classmethod
    def transition_order(cls, order: Order, new_state: str, notes: str = "") -> Order:
        """
        Transitions the order to a new state atomically, logging the event.
        Validates whether the transition is allowed.
        """
        if new_state not in cls.VALID_TRANSITIONS.get(order.state, []):
            raise ValidationError(f"Invalid transition from {order.state} to {new_state}.")

        with transaction.atomic():
            locked_order = Order.objects.get(id=order.id)
            
            if new_state not in cls.VALID_TRANSITIONS.get(locked_order.state, []):
                raise ValidationError(f"Invalid transition from {locked_order.state} to {new_state}.")
            
            previous_state = locked_order.state
            locked_order.state = new_state
            locked_order.save(update_fields=['state', 'updated_at'])

            if new_state == Order.State.PAID and locked_order.customer:
                from django.db.models import F
                locked_order.customer.__class__.objects.filter(pk=locked_order.customer_id).update(
                    loyalty_points=F('loyalty_points') + int(locked_order.total_amount)
                )

            OrderEventLog.objects.create(
                order=locked_order,
                previous_state=previous_state,
                new_state=new_state,
                notes=notes
            )

        # Emit WebSocket event after successful DB transaction
        cls.emit_update(locked_order)
        return locked_order

    @classmethod
    def emit_update(cls, order: Order):
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
