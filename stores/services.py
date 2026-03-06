from django.core.exceptions import ValidationError
from stores.models import Store
from orders.models import Order, OrderItem
from django.core.cache import cache
import json

class KitchenEngine:
    """
    Manages the queuing of items that require kitchen prep capacity.
    Uses Django's cache to manage a FIFO queue of items.
    """

    @staticmethod
    def _queue_key(store_id: int):
        return f"kitchen_queue_store_{store_id}"

    @classmethod
    def enqueue_order(cls, order: Order):
        """
        Pushes all prep-required items from an order into the store's kitchen queue.
        """
        items_to_prep = order.items.filter(product__requires_kitchen=True)
        if not items_to_prep.exists():
            return
        
        queue_key = cls._queue_key(order.store.id)
        current_queue = cache.get(queue_key, [])
        
        for item in items_to_prep:
            payload = {
                "order_id": order.id,
                "item_id": item.id,
                "qty": item.quantity,
                "prep_time": item.product.estimated_prep_time_minutes
            }
            current_queue.append(payload)
            
        cache.set(queue_key, current_queue, timeout=None)

    @classmethod
    def get_queue_size(cls, store: Store) -> int:
        return len(cache.get(cls._queue_key(store.id), []))
    
    @classmethod
    def peek_next_item(cls, store: Store):
        queue = cache.get(cls._queue_key(store.id), [])
        return queue[0] if queue else None

    @classmethod
    def pop_next_item(cls, store: Store):
        queue = cache.get(cls._queue_key(store.id), [])
        if not queue:
            return None
        item = queue.pop(0)
        cache.set(cls._queue_key(store.id), queue, timeout=None)
        return item
