from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum
from stores.models import Store
from orders.models import Order
from orders.services import OrderStateMachine
from billing.models import CommissionLedgerEntry, MonthlyInvoice
import calendar
import logging

logger = logging.getLogger(__name__)

@shared_task
def trigger_scheduled_orders():
    """
    Find paid scheduled orders where the prep start time has reached,
    and transition/enqueue them.
    """
    now = timezone.now()
    # Find paid scheduled orders whose scheduled start time has arrived
    due_orders = Order.objects.filter(
        state=Order.State.PAID,
        scheduled_start_time__lte=now,
        scheduled_time__isnull=False
    )
    for order in due_orders:
        try:
            has_kitchen_items = order.items.filter(product__requires_kitchen=True).exists()
            if order.store.store_type == 'SHOP' or not has_kitchen_items:
                # Shops and zero-prep orders don't have preparation queues, transition directly to READY
                OrderStateMachine.transition_order(order, Order.State.READY, notes="Scheduled order start time reached (Auto-ready).")
                logger.info(f"Scheduled order #{order.id} transitioned to READY.")
            else:
                # Restaurants enqueue in KitchenEngine
                from stores.services import KitchenEngine
                KitchenEngine.enqueue_order(order)
                OrderStateMachine.transition_order(order, Order.State.QUEUED, notes="Scheduled order start time reached (Enqueued in kitchen).")
                logger.info(f"Scheduled restaurant order #{order.id} enqueued and transitioned to QUEUED.")
        except Exception as e:
            logger.error(f"Failed to trigger scheduled order #{order.id}: {e}")

@shared_task
def generate_monthly_invoices():
    """
    Generates monthly commission invoices for all active stores
    for the previous month. Runs on the 1st of every month.
    """
    now = timezone.now()
    # Calculate previous month and year
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    prev_month = last_day_prev_month.month
    prev_year = last_day_prev_month.year
    
    # Start and end date for filtering ledger entries
    start_date = timezone.make_aware(timezone.datetime(prev_year, prev_month, 1, 0, 0, 0))
    # Number of days in prev_month
    _, num_days = calendar.monthrange(prev_year, prev_month)
    end_date = timezone.make_aware(timezone.datetime(prev_year, prev_month, num_days, 23, 59, 59, 999999))
    
    # 15 days from now is the invoice due date (e.g. 15th of the month)
    due_date = (first_of_this_month + timedelta(days=14)).date()

    for store in Store.objects.filter(is_active=True):
        # Calculate sum of order amounts and sum of commissions for this store in the previous month
        ledger_entries = CommissionLedgerEntry.objects.filter(
            store=store,
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        totals = ledger_entries.aggregate(
            total_orders=Sum('order_amount'),
            total_comm=Sum('commission_amount')
        )
        
        total_order_amount = totals['total_orders'] or 0
        total_commission = totals['total_comm'] or 0
        order_count = ledger_entries.filter(entry_type=CommissionLedgerEntry.EntryType.COMMISSION).count()
        
        # Only create invoice if there were orders or commission accrued
        if order_count > 0 or total_commission > 0:
            MonthlyInvoice.objects.get_or_create(
                store=store,
                year=prev_year,
                month=prev_month,
                defaults={
                    'total_order_amount': total_order_amount,
                    'total_commission': total_commission,
                    'order_count': order_count,
                    'status': MonthlyInvoice.Status.UNPAID,
                    'due_date': due_date
                }
            )
            logger.info(f"Generated invoice for store {store.name} for {prev_year}/{prev_month}.")
