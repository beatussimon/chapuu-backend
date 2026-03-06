from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from payments.models import Payment
from orders.services import OrderStateMachine
from orders.models import Order
import logging

logger = logging.getLogger(__name__)

@shared_task
def poll_pending_payments():
    """
    Fallback worker that polls Zenopay for payments stuck in PENDING status
    for more than 5 minutes. (Simulated integration for now).
    """
    threshold_time = timezone.now() - timedelta(minutes=5)
    stuck_payments = Payment.objects.filter(status=Payment.Status.PENDING, created_at__lte=threshold_time)

    for payment in stuck_payments:
        # In a real app, make an outbound requests.get() to Zenopay /status endpoint
        # For simulation, we assume if it's been 15 minutes, it just failed.
        if timezone.now() - payment.created_at > timedelta(minutes=15):
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=['status'])
            
            if payment.order:
                try:
                    OrderStateMachine.transition_order(payment.order, Order.State.CANCELLED, notes="Payment timeout via fallback polling.")
                except Exception as e:
                     logger.error(f"Cancellation failed post-payment timeout: {e}")
            logger.info(f"Payment {payment.id} marked FAILED via polling worker.")
