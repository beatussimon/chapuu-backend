from django.db import transaction
from django.core.exceptions import ValidationError
from catalog.models import InventoryStock
from orders.models import Order

class InventoryEngine:
    @classmethod
    def deduct_stock_for_order(cls, order: Order):
        """
        Atomically deducts inventory stock for all items in the order.
        Raises ValidationError if there is insufficient stock or over-booking.
        """
        with transaction.atomic():
            for item in order.items.all():
                if item.product.requires_inventory:
                    # Handle direct product stock
                    if hasattr(item.product, 'stock') and item.product.stock is not None:
                        stock = item.product.stock
                        if stock.quantity < item.quantity:
                            raise ValidationError(f"Insufficient stock for {item.product.name}.")
                        stock.quantity -= item.quantity
                        stock.save(update_fields=['quantity'])
                    else:
                        raise ValidationError(f"Product {item.product.name} requires inventory but has no stock tracking set up.")
