from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from catalog.models import Product, Category
from stores.models import Store

def invalidate_discovery_caches():
    """
    Clears the most expensive discovery-related cache keys.
    """
    keys_to_clear = [
        "billboard_stats_global",
        "all_stores_list",
    ]
    # We use a pattern to clear location-specific caches if needed
    # For now, we focus on the global entry points
    for key in keys_to_clear:
        cache.delete(key)

@receiver([post_save, post_delete], sender=Store)
def store_change_handler(sender, instance, **kwargs):
    invalidate_discovery_caches()

@receiver([post_save, post_delete], sender=Product)
def product_change_handler(sender, instance, **kwargs):
    invalidate_discovery_caches()

@receiver([post_save, post_delete], sender=Category)
def category_change_handler(sender, instance, **kwargs):
    invalidate_discovery_caches()
