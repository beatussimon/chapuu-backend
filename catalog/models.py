from django.db import models
from stores.models import Store
from config.image_utils import compress_image

class Category(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='categories', null=True, blank=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Product(models.Model):
    class FulfillmentMode(models.TextChoices):
        TAKEAWAY = 'TAKEAWAY', 'Takeaway'
        DELIVERY = 'DELIVERY', 'Delivery'
        DINE_IN = 'DINE_IN', 'Dine-In'
        RESERVATION = 'RESERVATION', 'Reservation'

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    image2 = models.ImageField(upload_to='products/', null=True, blank=True)
    
    requires_inventory = models.BooleanField(default=False)
    requires_kitchen = models.BooleanField(default=False)
    estimated_prep_time_minutes = models.PositiveIntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Round price to nearest integer only if it is very close (diff < 0.05), which perfectly filters exchange rate rounding noise while preserving valid decimals (e.g. 15.50)
        if self.price is not None:
            from decimal import Decimal
            price_val = Decimal(str(self.price))
            nearest_int = price_val.quantize(Decimal('1.'))
            if abs(price_val - nearest_int) < Decimal('0.05'):
                self.price = nearest_int

        # Auto-compress images to WebP on new upload
        if self.image and hasattr(self.image, 'file'):
            try:
                compressed = compress_image(self.image)
                if compressed and compressed is not self.image:
                    self.image = compressed
            except Exception:
                pass  # Keep original if compression fails
        if self.image2 and hasattr(self.image2, 'file'):
            try:
                compressed2 = compress_image(self.image2)
                if compressed2 and compressed2 is not self.image2:
                    self.image2 = compressed2
            except Exception:
                pass
        super().save(*args, **kwargs)

    def get_average_prep_time(self):
        """
        Intelligently calculates the average preparation time for this specific product based on past orders.
        Falls back to estimated_prep_time_minutes if not enough historical data exists.
        """
        from orders.models import OrderEventLog
        
        # Query distinct completed order IDs that contained this product
        order_ids = self.order_items.filter(order__state='COMPLETED').values_list('order_id', flat=True).distinct()
        
        if len(order_ids) >= 3:
            preparing_logs = OrderEventLog.objects.filter(order_id__in=order_ids, new_state='PREPARING')
            ready_logs = OrderEventLog.objects.filter(order_id__in=order_ids, new_state='READY')
            
            prep_times = []
            for order_id in order_ids:
                p_log = preparing_logs.filter(order_id=order_id).first()
                r_log = ready_logs.filter(order_id=order_id).first()
                if p_log and r_log and r_log.created_at > p_log.created_at:
                    duration = (r_log.created_at - p_log.created_at).total_seconds() / 60.0
                    prep_times.append(duration)
            
            if len(prep_times) >= 3:
                avg_time = sum(prep_times) / len(prep_times)
                return max(int(avg_time), 1)  # Ensure at least 1 minute
                
        # Fallback to estimated prep time
        fallback = self.estimated_prep_time_minutes
        if fallback == 0:
            from stores.models import KitchenSettings
            try:
                kitchen_settings = self.store.kitchen_settings
                fallback = kitchen_settings.default_prep_time_minutes
            except KitchenSettings.DoesNotExist:
                fallback = 15  # Default fallback duration
        return fallback

    def check_stock_available(self, quantity=1):
        """
        Checks if the requested quantity is available in stock.
        Handles direct packaged stock (requires_inventory) and recipe ingredients (requires_kitchen).
        Returns a tuple: (is_available, error_message, available_qty)
        """
        if self.requires_inventory:
            if not hasattr(self, 'stock') or self.stock is None:
                return False, f"Product {self.name} is out of stock.", 0
            if self.stock.quantity < quantity:
                return False, f"Only {self.stock.quantity} available for {self.name}.", self.stock.quantity
            
        if self.requires_kitchen:
            for recipe_item in self.recipe_ingredients.select_related('ingredient__stock').all():
                if not hasattr(recipe_item.ingredient, 'stock') or recipe_item.ingredient.stock is None:
                    return False, f"Ingredient {recipe_item.ingredient.name} is out of stock.", 0
                
                required_qty = recipe_item.quantity_required * quantity
                available = recipe_item.ingredient.stock.quantity
                if available < required_qty:
                    max_possible = int(available / recipe_item.quantity_required)
                    return False, f"Insufficient ingredients for {self.name}.", max_possible
                        
        return True, "", None

    def __str__(self):
        return self.name

class Ingredient(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='ingredients')
    name = models.CharField(max_length=100)
    unit_of_measure = models.CharField(max_length=50) # e.g., kg, liters, pieces
    image = models.ImageField(upload_to='ingredients/', null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.unit_of_measure})"

class InventoryStock(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='stock', null=True, blank=True)
    ingredient = models.OneToOneField(Ingredient, on_delete=models.CASCADE, related_name='stock', null=True, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(product__isnull=False, ingredient__isnull=True) |
                    models.Q(product__isnull=True, ingredient__isnull=False)
                ),
                name='stock_must_belong_to_product_or_ingredient'
            )
        ]

    def __str__(self):
        target = self.product.name if self.product_id else (self.ingredient.name if self.ingredient_id else "ORPHAN")
        return f"Stock for {target}: {self.quantity}"

class RecipeIngredient(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='recipe_ingredients')
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name='recipes')
    quantity_required = models.DecimalField(max_digits=10, decimal_places=2, default=1.0)
    
    class Meta:
        unique_together = ('product', 'ingredient')

    def __str__(self):
        return f"{self.quantity_required} {self.ingredient.unit_of_measure} of {self.ingredient.name} for {self.product.name}"

class StockAdjustmentLog(models.Model):
    stock = models.ForeignKey(InventoryStock, on_delete=models.CASCADE, related_name='adjustment_logs')
    previous_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    new_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Stock change for {self.stock}: {self.previous_quantity} -> {self.new_quantity} ({self.reason})"
