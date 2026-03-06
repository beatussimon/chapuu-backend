from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from orders.models import Order
from orders.services import OrderStateMachine
from reservations.models import Reservation
import logging

logger = logging.getLogger(__name__)

@shared_task
def expire_unpaid_orders():
    """
    Finds orders that have been awaiting payment for more than 15 minutes
    and transitions them to EXPIRED.
    """
    expiry_time = timezone.now() - timedelta(minutes=15)
    expired_orders = Order.objects.filter(state=Order.State.AWAITING_PAYMENT, updated_at__lte=expiry_time)

    for order in expired_orders:
        try:
            OrderStateMachine.transition_order(order, Order.State.EXPIRED, notes="Unpaid order timeout.")
            logger.info(f"Order #{order.id} marked as EXPIRED.")
        except Exception as e:
            logger.error(f"Failed to expire order #{order.id}: {e}")

@shared_task
def expire_no_show_reservations():
    """
    Cancels reservations if the guest hasn't arrived within 30 minutes of 
    their scheduled time.
    """
    expiry_time = timezone.now() - timedelta(minutes=30)
    no_shows = Reservation.objects.filter(
        status__in=[Reservation.Status.CONFIRMED, Reservation.Status.PENDING],
        reservation_time__lte=expiry_time
    )

    for res in no_shows:
        res.status = Reservation.Status.NO_SHOW
        res.save(update_fields=['status'])
        logger.info(f"Reservation {res.id} marked as NO_SHOW.")
