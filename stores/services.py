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
        Uses a basic lock pattern to ensure atomicity.
        """
        items_to_prep = order.items.filter(product__requires_kitchen=True)
        if not items_to_prep.exists():
            return
        
        queue_key = cls._queue_key(order.store.id)
        lock_key = f"{queue_key}_lock"
        
        # Simple spin-lock
        import time
        acquired = False
        for _ in range(50): # try for 5 seconds
            if cache.add(lock_key, "locked", timeout=10):
                acquired = True
                break
            time.sleep(0.1)
            
        if not acquired:
            # Fallback: log error but don't crash
            print(f"ERROR: Could not acquire lock for kitchen queue {queue_key}")
            return

        try:
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
        finally:
            cache.delete(lock_key)

    @classmethod
    def get_queue_size(cls, store: Store) -> int:
        return len(cache.get(cls._queue_key(store.id), []))
    
    @classmethod
    def peek_next_item(cls, store: Store):
        queue = cache.get(cls._queue_key(store.id), [])
        return queue[0] if queue else None

    @classmethod
    def pop_next_item(cls, store: Store):
        queue_key = cls._queue_key(store.id)
        lock_key = f"{queue_key}_lock"
        
        # Simple spin-lock
        import time
        acquired = False
        for _ in range(50):
            if cache.add(lock_key, "locked", timeout=10):
                acquired = True
                break
            time.sleep(0.1)
            
        if not acquired:
            return None

        try:
            queue = cache.get(queue_key, [])
            if not queue:
                return None
            item = queue.pop(0)
            cache.set(queue_key, queue, timeout=None)
            return item
        finally:
            cache.delete(lock_key)
