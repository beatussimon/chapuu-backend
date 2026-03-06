from celery import shared_task
from stores.models import Store
from stores.services import KitchenEngine
from orders.models import OrderItem, Order
import logging

logger = logging.getLogger(__name__)

@shared_task
def process_kitchen_queues():
    """
    Evaluates kitchen capacity for all active stores and moves queue items
    to PREPARING if parallel slots are available.
    """
    stores = Store.objects.filter(is_active=True, kitchen_settings__is_kitchen_paused=False)
    
    for store in stores:
        settings = store.kitchen_settings
        
        # Determine currently preparing items for this store
        preparing_count = OrderItem.objects.filter(
            order__store=store,
            order__state__in=[Order.State.QUEUED, Order.State.PREPARING],
            is_ready=False,
            product__requires_kitchen=True
        ).count()
        
        available_slots = settings.max_concurrent_prep_slots - preparing_count
        
        while available_slots > 0:
            next_item = KitchenEngine.peek_next_item(store)
            if not next_item:
                break # Queue empty
                
            # Pop the item and push it to preparing (DB representation handles "preparing" state usually)
            popped_item = KitchenEngine.pop_next_item(store)
            if popped_item:
                # Mark order state as preparing if not already
                order = Order.objects.get(id=popped_item['order_id'])
                if order.state == Order.State.QUEUED:
                    from orders.services import OrderStateMachine
                    OrderStateMachine.transition_order(order, Order.State.PREPARING, notes="Kitchen prep started")
                
                logger.info(f"Started preparing item {popped_item['item_id']} for order {order.id}")
                available_slots -= 1
