from django.db import transaction
from django.core.exceptions import ValidationError
from orders.models import Order, OrderEventLog

class OrderStateMachine:
    VALID_TRANSITIONS = {
        Order.State.CREATED: [Order.State.AWAITING_PAYMENT, Order.State.CANCELLED],
        Order.State.AWAITING_PAYMENT: [Order.State.PAID, Order.State.CANCELLED, Order.State.EXPIRED],
        Order.State.PAID: [Order.State.QUEUED, Order.State.PREPARING, Order.State.READY, Order.State.REFUNDED],  # READY added for shop flow
        Order.State.QUEUED: [Order.State.PREPARING, Order.State.CANCELLED, Order.State.REFUNDED],
        Order.State.PREPARING: [Order.State.READY, Order.State.CANCELLED, Order.State.REFUNDED],
        Order.State.READY: [Order.State.COMPLETED, Order.State.REFUNDED],
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
            # In a real app with Postgres, use `select_for_update` to lock the row.
            # SQLite does file-level locking, so this is safe sequentially but not totally concurrent-proof.
            locked_order = Order.objects.get(id=order.id)
            
            # Double check state hasn't changed
            if new_state not in cls.VALID_TRANSITIONS.get(locked_order.state, []):
                raise ValidationError(f"Invalid transition from {locked_order.state} to {new_state}.")
            
            previous_state = locked_order.state
            locked_order.state = new_state
            locked_order.save(update_fields=['state', 'updated_at'])

            OrderEventLog.objects.create(
                order=locked_order,
                previous_state=previous_state,
                new_state=new_state,
                notes=notes
            )

            return locked_order
