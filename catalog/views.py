from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from catalog.models import Product, Category, InventoryStock, Ingredient, RecipeIngredient
from catalog.serializers import ProductSerializer, CategorySerializer, InventoryStockSerializer, IngredientSerializer, RecipeIngredientSerializer
from decimal import Decimal, InvalidOperation

class IsSellerOrAdminForWrite(permissions.BasePermission):
    """Allow anyone to read, but only SELLER/ADMIN to write."""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return (
            request.user.is_authenticated and
            request.user.role in ['SELLER', 'ADMIN']
        )

class ProductViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for products.
    - Customers see only active products (read-only via permissions).
    - Sellers see all their own products and can create/update/delete.
    - Admins see everything.
    """
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [IsSellerOrAdminForWrite]

    def get_queryset(self):
        queryset = super().get_queryset()
        # If user is a seller, they should see all their products, even inactive ones
        if self.request.user.is_authenticated and self.request.user.role in ['SELLER', 'ADMIN']:
            queryset = Product.objects.all()
            
        store_id = self.request.query_params.get('store', None)
        category_id = self.request.query_params.get('category', None)
        if store_id is not None:
            queryset = queryset.filter(store_id=store_id)
        if category_id is not None:
            queryset = queryset.filter(category_id=category_id)
            
        # If user is a seller, restrict to their store only
        if self.request.user.is_authenticated and self.request.user.role == 'SELLER':
            queryset = queryset.filter(store__owner=self.request.user)
            
        return queryset

    def perform_update(self, serializer):
        product = serializer.save()
        initial_stock = self.request.data.get('initial_stock')
        if product.requires_inventory and initial_stock is not None:
            try:
                stock_qty = Decimal(str(initial_stock))
                stock, created = InventoryStock.objects.get_or_create(product=product)
                stock.quantity = stock_qty
                stock.save()
            except (ValueError, TypeError, InvalidOperation):
                pass

    def destroy(self, request, *args, **kwargs):
        """Soft-delete: mark product inactive instead of hard-deleting.
        This avoids 500 errors from PROTECT foreign keys on OrderItem."""
        product = self.get_object()
        product.is_active = False
        product.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def toggle_status(self, request, pk=None):
        """Seller action: Toggle product is_active to manually mark out-of-stock"""
        product = self.get_object()
        if request.user.role != 'SELLER' and request.user.role != 'ADMIN':
             return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
             
        product.is_active = not product.is_active
        product.save()
        return Response({"status": "toggled", "is_active": product.is_active})

    @action(detail=False, methods=['get'])
    def recommendations(self, request):
        """
        AI-Powered Recommendations Endpoint (Simulated)
        In a real scenario, this would call a recommendation engine.
        For now, it returns 3 random active products biased towards the current store if provided.
        """
        queryset = self.get_queryset()
        
        # Simple randomization for demonstration
        recommendations = queryset.order_by('?')[:3]
        serializer = self.get_serializer(recommendations, many=True)
        return Response(serializer.data)

class CategoryViewSet(viewsets.ModelViewSet):
    """
    CRUD view for sellers and admins to manage categories, read-only for customers.
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        store_id = self.request.query_params.get('store', None)
        if store_id is not None:
            queryset = queryset.filter(store_id=store_id)
        return queryset

class InventoryStockViewSet(viewsets.ModelViewSet):
    """
    CRUD view for sellers to manage inventory levels.
    """
    serializer_class = InventoryStockSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'SELLER':
            return InventoryStock.objects.filter(product__store__owner=user) | InventoryStock.objects.filter(ingredient__store__owner=user)
        elif user.role == 'ADMIN':
            return InventoryStock.objects.all()
        return InventoryStock.objects.none()

    @action(detail=True, methods=['post'])
    def adjust(self, request, pk=None):
        """Manually adjust stock (restock/deduct)"""
        stock = self.get_object()
        if request.user.role != 'SELLER' and request.user.role != 'ADMIN':
             return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
             
        adjustment = request.data.get('adjustment', 0)
        try:
            adjustment = Decimal(str(adjustment))
            if stock.quantity + adjustment < Decimal('0'):
                return Response({"error": "Stock cannot be negative"}, status=status.HTTP_400_BAD_REQUEST)
                
            stock.quantity += adjustment
            stock.save()
            return Response({"status": "Stock adjusted", "new_quantity": stock.quantity})
        except (ValueError, TypeError, InvalidOperation):
            return Response({"error": "Invalid adjustment amount"}, status=status.HTTP_400_BAD_REQUEST)

class IngredientViewSet(viewsets.ModelViewSet):
    serializer_class = IngredientSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'SELLER':
            return Ingredient.objects.filter(store__owner=user)
        elif user.role == 'ADMIN':
            return Ingredient.objects.all()
        return Ingredient.objects.none()

class RecipeIngredientViewSet(viewsets.ModelViewSet):
    serializer_class = RecipeIngredientSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'SELLER':
            return RecipeIngredient.objects.filter(product__store__owner=user)
        elif user.role == 'ADMIN':
            return RecipeIngredient.objects.all()
        return RecipeIngredient.objects.none()
