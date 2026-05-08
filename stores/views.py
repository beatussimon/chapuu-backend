from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from stores.models import Store, KitchenSettings, Advertisement, CurrencyConfig, Table, Notice, StorePaymentMethod
from stores.serializers import StoreSerializer, KitchenSettingsSerializer, AdvertisementSerializer, CurrencyConfigSerializer, TableSerializer, NoticeSerializer, StorePaymentMethodSerializer
from stores.services import KitchenEngine
from reviews.models import StoreReview
from reviews.serializers import StoreReviewSerializer

class IsSellerOrAdminForWriteStore(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and request.user.role in ['SELLER', 'ADMIN']

class StorePaymentMethodViewSet(viewsets.ModelViewSet):
    serializer_class = StorePaymentMethodSerializer
    permission_classes = [IsSellerOrAdminForWriteStore]

    def get_queryset(self):
        # Allow sellers/admins to see all payment methods, public to see only active
        user = self.request.user
        if user.is_authenticated and user.role in ['SELLER', 'ADMIN']:
            queryset = StorePaymentMethod.objects.all()
        else:
            queryset = StorePaymentMethod.objects.filter(is_active=True)
            
        store_id = self.request.query_params.get('store', None)
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        return queryset

    def perform_create(self, serializer):
        store = serializer.validated_data.get('store')
        if self.request.user.role != 'ADMIN' and store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only add payment methods to your own store.")
        serializer.save()

    def perform_update(self, serializer):
        payment_method = self.get_object()
        if self.request.user.role != 'ADMIN' and payment_method.store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only modify payment methods for your own store.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role != 'ADMIN' and instance.store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only delete payment methods for your own store.")
        instance.delete()

class NoticeViewSet(viewsets.ModelViewSet):
    serializer_class = NoticeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return Notice.objects.all()
        elif user.role == 'SELLER':
            return Notice.objects.filter(Q(store__owner=user) | Q(store__isnull=True))
        else:
            # Staff can see notices for their store or global ones
            qs = Notice.objects.filter(Q(target_user=user) | Q(target_user__isnull=True))
            if user.employed_store:
                qs = qs.filter(Q(store=user.employed_store) | Q(store__isnull=True))
            else:
                qs = qs.filter(store__isnull=True)
            return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class CurrencyConfigViewSet(viewsets.ReadOnlyModelViewSet):
    """Public read-only endpoint for active currencies and exchange rates."""
    queryset = CurrencyConfig.objects.filter(is_active=True)
    serializer_class = CurrencyConfigSerializer
    permission_classes = [permissions.AllowAny]

class TableViewSet(viewsets.ModelViewSet):
    """CRUD for tables. Read-only for customers, full CRUD for sellers/admins."""
    serializer_class = TableSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Table.objects.filter(is_active=True)
        store_id = self.request.query_params.get('store', None)
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        return queryset

class AdvertisementViewSet(viewsets.ModelViewSet):
    queryset = Advertisement.objects.filter(is_active=True)
    serializer_class = AdvertisementSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        store_id = self.request.query_params.get('store', None)
        
        if store_id:
            # Return global ads (store=None) OR ads for this specific store
            queryset = queryset.filter(store__isnull=True) | queryset.filter(store_id=store_id)
        else:
            # If no store specified, return global ads
            queryset = queryset.filter(store__isnull=True)
            
        return queryset

class StoreViewSet(viewsets.ModelViewSet):
    queryset = Store.objects.filter(is_active=True).prefetch_related('payment_methods', 'kitchen_settings')
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print("STORE CREATION VALIDATION ERROR:", serializer.errors)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)
        
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def my_store(self, request):
        user = request.user
        if user.role not in ['SELLER', 'ADMIN', 'CHEF', 'ACCOUNTANT', 'DELIVERY']:
            return Response({"error": f"Unauthorized. Your role is {user.role}"}, status=403)
            
        store = None
        
        # 1. Try to find store by ownership (Sellers)
        if user.role == 'SELLER':
            store = Store.objects.filter(owner=user, is_active=True).first()
            
        # 2. Try to find store by employment (Chefs/Staff)
        if not store and user.employed_store:
            store = user.employed_store

        # 3. Try to find store for ACCOUNTANT/DELIVERY
        if not store and user.role in ['ACCOUNTANT', 'DELIVERY'] and user.employed_store:
            store = user.employed_store
            
        # 3. Fallback for ADMIN (See any active store to avoid dashboard crash)
        if not store and user.role == 'ADMIN':
            store = Store.objects.filter(is_active=True).first()
            
        if store:
            serializer = self.get_serializer(store)
            return Response(serializer.data)
            
        return Response({"error": "No active store found for your account."}, status=404)
    
    @action(detail=True, methods=['get', 'post'])
    def tables(self, request, pk=None):
        store = self.get_object()
        
        if request.method == 'POST':
            number = request.data.get('number')
            capacity = request.data.get('capacity', 2)
            if not number:
                return Response({"error": "Table number is required"}, status=400)
            table = store.tables.create(number=number, capacity=capacity)
            return Response({'id': table.id, 'number': table.number, 'capacity': table.capacity, 'is_active': table.is_active}, status=201)
            
        tables = store.tables.all().values('id', 'number', 'capacity', 'is_active')
        return Response(tables)

    @action(detail=True, methods=['get'])
    def kitchen_queue(self, request, pk=None):
        store = self.get_object()
        q_size = KitchenEngine.get_queue_size(store)
        return Response({"queue_size": q_size})
        
    @action(detail=True, methods=['patch'])
    def toggle_status(self, request, pk=None):
        store = self.get_object()
        if request.user != store.owner and request.user.role != 'ADMIN':
            return Response({"error": "unauthorized"}, status=403)
            
        store.is_open = not store.is_open
        store.save(update_fields=['is_open'])
        return Response({"is_open": store.is_open})

    @action(detail=True, methods=['patch'])
    def toggle_kitchen_pause(self, request, pk=None):
        store = self.get_object()
        if request.user != store.owner and request.user.role != 'ADMIN':
            return Response({"error": "unauthorized"}, status=403)
            
        settings = store.kitchen_settings
        settings.is_kitchen_paused = not settings.is_kitchen_paused
        settings.save()
        return Response({"paused": settings.is_kitchen_paused})

    @action(detail=True, methods=['get'])
    def reviews(self, request, pk=None):
        store = self.get_object()
        reviews = StoreReview.objects.filter(store=store).order_by('-created_at')
        serializer = StoreReviewSerializer(reviews, many=True)
        return Response(serializer.data)
