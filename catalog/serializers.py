from rest_framework import serializers
from catalog.models import Product, Category, InventoryStock, Ingredient, RecipeIngredient
from stores.models import Store

class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    image2_url = serializers.SerializerMethodField()
    stock_quantity = serializers.SerializerMethodField()
    computed_is_available = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'store', 'category', 'category_name', 'name', 'description',
            'price', 'image', 'image_url', 'image2', 'image2_url', 'requires_inventory', 'requires_kitchen',
            'estimated_prep_time_minutes', 'is_active', 'created_at',
            'stock_quantity', 'computed_is_available'
        ]

    def get_category_name(self, obj):
        if obj.category:
            return obj.category.name
        return 'Uncategorized'

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_image2_url(self, obj):
        if getattr(obj, 'image2', None):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image2.url)
            return obj.image2.url
        return None

    def get_stock_quantity(self, obj):
        if obj.requires_inventory:
            try:
                return obj.stock.quantity
            except Exception:
                return 0
        return None

    def get_computed_is_available(self, obj):
        if not obj.is_active:
            return False
        if obj.requires_inventory:
            try:
                return obj.stock.quantity > 0
            except Exception:
                return False
        return True

class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Category
        fields = '__all__'

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()

class InventoryStockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)

    class Meta:
        model = InventoryStock
        fields = ['id', 'product', 'product_name', 'ingredient', 'ingredient_name', 'quantity', 'low_stock_threshold']

class IngredientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ingredient
        fields = '__all__'

class RecipeIngredientSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)
    unit_of_measure = serializers.CharField(source='ingredient.unit_of_measure', read_only=True)
    
    class Meta:
        model = RecipeIngredient
        fields = ['id', 'product', 'ingredient', 'ingredient_name', 'unit_of_measure', 'quantity_required']
