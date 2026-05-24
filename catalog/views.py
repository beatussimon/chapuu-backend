from rest_framework import viewsets, permissions, status
from django.db.models import Q
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
            (request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER'] or request.user.is_superuser)
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
        user = self.request.user
        queryset = Product.objects.all()

        # Isolate by Role
        if not user.is_authenticated:
            queryset = Product.objects.filter(is_active=True, store__is_active=True)
        elif user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            pass # See all
        elif user.role == 'SELLER':
            queryset = queryset.filter(store__owner=user)
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY'] and user.employed_store:
            queryset = queryset.filter(store=user.employed_store)
        else:
            queryset = Product.objects.filter(is_active=True, store__is_active=True)
            
        store_id = self.request.query_params.get('store', None)
        category_id = self.request.query_params.get('category', None)
        if store_id is not None:
            queryset = queryset.filter(store_id=store_id)
        if category_id is not None:
            queryset = queryset.filter(category_id=category_id)
            
        return queryset

    def perform_create(self, serializer):
        product = serializer.save()
        self._handle_initial_stock(product)

    def perform_update(self, serializer):
        product = serializer.save()
        self._handle_initial_stock(product)

    def _handle_initial_stock(self, product):
        initial_stock = self.request.data.get('initial_stock')
        
        # Check if initial_stock was actually provided in the request
        if initial_stock is not None:
            stripped = str(initial_stock).strip()
            if stripped != '':
                try:
                    stock_qty = Decimal(stripped)
                    # If valid quantity provided (even 0), track inventory
                    product.requires_inventory = True
                    product.save(update_fields=['requires_inventory'])
                    
                    stock, created = InventoryStock.objects.get_or_create(product=product)
                    stock.quantity = stock_qty
                    stock.save()
                except (ValueError, TypeError, InvalidOperation):
                    # Fallback for invalid numeric input
                    pass
            else:
                 # Explicitly sent empty string -> Disable inventory tracking
                 product.requires_inventory = False
                 product.save(update_fields=['requires_inventory'])
                 # Optionally delete the stock record if it exists
                 InventoryStock.objects.filter(product=product).delete()

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
        is_seller_admin_su = request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER'] or request.user.is_superuser
        if not is_seller_admin_su:
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
            queryset = queryset.filter(Q(store__isnull=True) | Q(store_id=store_id))
        return queryset

    def create(self, request, *args, **kwargs):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({"detail": "Name is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Lowercase both and compare to prevent duplicates
        existing = Category.objects.filter(name__iexact=name).first()
        if existing:
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        data = request.data.copy()
        data['store'] = None
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

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
        elif user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return InventoryStock.objects.all()
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY'] and user.employed_store:
            return InventoryStock.objects.filter(product__store=user.employed_store) | InventoryStock.objects.filter(ingredient__store=user.employed_store)
        return InventoryStock.objects.none()

    @action(detail=True, methods=['post'])
    def adjust(self, request, pk=None):
        """Manually adjust stock (restock/deduct)"""
        stock = self.get_object()
        if request.user.role not in ['SELLER', 'ADMIN', 'SUPERUSER', 'CHEF'] and not request.user.is_superuser:
             return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
             
        adjustment = request.data.get('adjustment', 0)
        try:
            adjustment = Decimal(str(adjustment))
            if stock.quantity + adjustment < Decimal('0'):
                return Response({"error": "Stock cannot be negative"}, status=status.HTTP_400_BAD_REQUEST)
                
            previous_qty = stock.quantity
            stock.quantity += adjustment
            stock.save()
            
            # Log the adjustment
            StockAdjustmentLog.objects.create(
                stock=stock,
                previous_quantity=previous_qty,
                new_quantity=stock.quantity,
                reason=f"Manual adjustment by {request.user.username}"
            )
            
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
        elif user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return Ingredient.objects.all()
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY'] and user.employed_store:
            return Ingredient.objects.filter(store=user.employed_store)
        return Ingredient.objects.none()

class RecipeIngredientViewSet(viewsets.ModelViewSet):
    serializer_class = RecipeIngredientSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'SELLER':
            return RecipeIngredient.objects.filter(product__store__owner=user)
        elif user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return RecipeIngredient.objects.all()
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY'] and user.employed_store:
            return RecipeIngredient.objects.filter(product__store=user.employed_store)
        return RecipeIngredient.objects.none()
