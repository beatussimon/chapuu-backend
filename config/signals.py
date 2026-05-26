from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from catalog.models import Product, Category
from stores.models import Store

def invalidate_discovery_caches():
    """Clears global high-level caches."""
    keys = ["billboard_stats_global", "all_stores_list_page_1"]
    for k in keys:
        cache.delete(k)

def invalidate_store_cache(store_id):
    """Clears all caches related to a specific store."""
    keys = [
        f"store_detail_{store_id}",
        f"store_menu_{store_id}",
    ]
    for k in keys:
        cache.delete(k)
    # Also clear global lists since store data changed
    invalidate_discovery_caches()

@receiver([post_save, post_delete], sender=Store)
def store_change_handler(sender, instance, **kwargs):
    invalidate_store_cache(instance.id)

@receiver([post_save, post_delete], sender=Product)
def product_change_handler(sender, instance, **kwargs):
    invalidate_store_cache(instance.store_id)

@receiver([post_save, post_delete], sender=Category)
def category_change_handler(sender, instance, **kwargs):
    cache.delete("all_categories")
    invalidate_discovery_caches()
    # If it's a store-specific category, clear that store
    if instance.store_id:
        invalidate_store_cache(instance.store_id)
