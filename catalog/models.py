from django.db import models
from stores.models import Store
from config.image_utils import compress_image

class Category(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='categories')
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
