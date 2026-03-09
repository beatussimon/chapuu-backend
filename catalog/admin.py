from django.contrib import admin
from catalog.models import Category, Product, Ingredient, InventoryStock, RecipeIngredient, StockAdjustmentLog

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'store')
    list_filter = ('store',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'category', 'price', 'is_active')
    list_filter = ('store', 'category', 'is_active')
    search_fields = ('name',)

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'unit_of_measure')
    list_filter = ('store',)

@admin.register(InventoryStock)
class InventoryStockAdmin(admin.ModelAdmin):
    list_display = ('get_target', 'quantity', 'low_stock_threshold')
    def get_target(self, obj):
        return obj.product.name if obj.product else obj.ingredient.name
    get_target.short_description = 'Target'

@admin.register(RecipeIngredient)
class RecipeIngredientAdmin(admin.ModelAdmin):
    list_display = ('product', 'ingredient', 'quantity_required')

@admin.register(StockAdjustmentLog)
class StockAdjustmentLogAdmin(admin.ModelAdmin):
    list_display = ('stock', 'previous_quantity', 'new_quantity', 'reason', 'created_at')
