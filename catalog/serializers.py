from rest_framework import serializers
from catalog.models import Product, Category, InventoryStock, Ingredient, RecipeIngredient

class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'store', 'category', 'category_name', 'name', 'description',
            'price', 'image', 'image_url', 'requires_inventory', 'requires_kitchen',
            'estimated_prep_time_minutes', 'is_active', 'created_at'
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

class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

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
