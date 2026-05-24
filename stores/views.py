from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from stores.models import Store, KitchenSettings, Advertisement, CurrencyConfig, Table, Notice, StorePaymentMethod, SystemSupportConfig, StoreGalleryImage, GlobalPaymentMethod
from stores.serializers import StoreSerializer, KitchenSettingsSerializer, AdvertisementSerializer, CurrencyConfigSerializer, TableSerializer, NoticeSerializer, StorePaymentMethodSerializer, SystemSupportConfigSerializer, StoreGalleryImageSerializer, GlobalPaymentMethodSerializer
from stores.services import KitchenEngine
from reviews.models import StoreReview
from reviews.serializers import StoreReviewSerializer

class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and (request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser)

class IsSuperUserOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and (request.user.role == 'SUPERUSER' or request.user.is_superuser)

class GlobalPaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = GlobalPaymentMethod.objects.all()
    serializer_class = GlobalPaymentMethodSerializer
    permission_classes = [IsSuperUserOrReadOnly]

class IsSellerOrAdminForWriteStore(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and (request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER'] or request.user.is_superuser)

class StorePaymentMethodViewSet(viewsets.ModelViewSet):
    serializer_class = StorePaymentMethodSerializer
    permission_classes = [IsSellerOrAdminForWriteStore]

    def get_queryset(self):
        # Allow sellers/admins to see all payment methods, public to see only active
        user = self.request.user
        if user.is_authenticated and (user.role in ['SELLER', 'ADMIN', 'SUPERUSER'] or user.is_superuser):
            queryset = StorePaymentMethod.objects.all()
        else:
            queryset = StorePaymentMethod.objects.filter(is_active=True)
            
        store_id = self.request.query_params.get('store', None)
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        return queryset

    def perform_create(self, serializer):
        store = serializer.validated_data.get('store')
        is_admin_or_su = self.request.user.role in ['ADMIN', 'SUPERUSER'] or self.request.user.is_superuser
        if not is_admin_or_su and store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only add payment methods to your own store.")
        serializer.save()

    def perform_update(self, serializer):
        payment_method = self.get_object()
        is_admin_or_su = self.request.user.role in ['ADMIN', 'SUPERUSER'] or self.request.user.is_superuser
        if not is_admin_or_su and payment_method.store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only modify payment methods for your own store.")
        serializer.save()

    def perform_destroy(self, instance):
        is_admin_or_su = self.request.user.role in ['ADMIN', 'SUPERUSER'] or self.request.user.is_superuser
        if not is_admin_or_su and instance.store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only delete payment methods for your own store.")
        instance.delete()

class StoreGalleryImageViewSet(viewsets.ModelViewSet):
    serializer_class = StoreGalleryImageSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = StoreGalleryImage.objects.all()
        store_id = self.request.query_params.get('store', None)
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        return queryset

    def perform_create(self, serializer):
        store = serializer.validated_data.get('store')
        
        # 1. Authorization check: Only store owner or Admin/Superuser
        is_admin_or_su = self.request.user.role in ['ADMIN', 'SUPERUSER'] or self.request.user.is_superuser
        if not is_admin_or_su and store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only add gallery images to your own store.")
            
        # 2. Strict 10-image limit check
        if store.gallery_images.count() >= 10:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("You have reached the maximum limit of 10 gallery images for this store.")
            
        serializer.save()

    def perform_destroy(self, instance):
        # Authorization check: Only store owner or Admin/Superuser
        is_admin_or_su = self.request.user.role in ['ADMIN', 'SUPERUSER'] or self.request.user.is_superuser
        if not is_admin_or_su and instance.store.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only delete gallery images for your own store.")
        instance.delete()

class NoticeViewSet(viewsets.ModelViewSet):
    serializer_class = NoticeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        from django.db.models import Q
        
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return Notice.objects.all()
        elif user.role == 'SELLER':
            return Notice.objects.filter(Q(store__owner=user) | Q(store__isnull=True))
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY']:
            # Staff see notices for their store, notices targeting them, or global ones
            store = user.employed_store
            if not store:
                store = Store.objects.first()
            return Notice.objects.filter(
                Q(store=store) | 
                Q(target_user=user) | 
                Q(store__isnull=True)
            )
        
        # Customers/Other only see global or specific targets
        return Notice.objects.filter(Q(target_user=user) | Q(store__isnull=True))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def mark_as_read(self, request, pk=None):
        notice = self.get_object()
        notice.read_by.add(request.user)
        return Response({"status": "Notice marked as read"})

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

from django.core.cache import cache

class StoreViewSet(viewsets.ModelViewSet):
    queryset = Store.objects.all().prefetch_related('payment_methods', 'kitchen_settings')
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user and user.is_authenticated and (user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser):
            return Store.objects.all().prefetch_related('payment_methods', 'kitchen_settings')
        return Store.objects.filter(is_active=True).prefetch_related('payment_methods', 'kitchen_settings')
    
    def list(self, request, *args, **kwargs):
        # Intelligent Caching for the main store list (no filters/params)
        # This drastically reduces DB load for the 'Browse' page
        if not request.query_params:
            cache_key = "all_stores_list"
            cached_data = cache.get(cache_key)
            if cached_data:
                return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        
        # Apply search filter
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(location__icontains=search))
            
        # Apply is_open filter
        is_open = request.query_params.get('is_open')
        if is_open in ['true', 'True', '1']:
            queryset = queryset.filter(is_open=True)
        elif is_open in ['false', 'False', '0']:
            queryset = queryset.filter(is_open=False)
            
        # Apply store_type filter
        store_type = request.query_params.get('store_type')
        if store_type:
            queryset = queryset.filter(store_type=store_type)

        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        
        if lat and lng:
            from stores.geo_utils import annotate_distances, filter_by_radius
            stores_list = annotate_distances(queryset, lat, lng)
            radius = request.query_params.get('radius')
            if radius:
                stores_list = filter_by_radius(stores_list, radius)
            
            page = self.paginate_queryset(stores_list)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            
            serializer = self.get_serializer(stores_list, many=True)
            return Response(serializer.data)
            
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        
        if not request.query_params:
            cache.set("all_stores_list", serializer.data, 60*60) # Cache for 1 hour
            
        return Response(serializer.data)

    
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
        if user.role not in ['SELLER', 'ADMIN', 'SUPERUSER', 'CHEF', 'ACCOUNTANT', 'DELIVERY']:
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
        if not store and (user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser):
            store = Store.objects.filter(is_active=True).first()
            
        # 4. Fallback for staff with no employed_store (Local/Test helper)
        if not store and user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY']:
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
        is_admin_or_su = request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser
        if request.user != store.owner and not is_admin_or_su:
            return Response({"error": "unauthorized"}, status=403)
            
        store.is_open = not store.is_open
        store.save(update_fields=['is_open'])
        return Response({"is_open": store.is_open})

    @action(detail=True, methods=['patch'])
    def toggle_kitchen_pause(self, request, pk=None):
        store = self.get_object()
        is_admin_or_su = request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser
        if request.user != store.owner and not is_admin_or_su:
            return Response({"error": "unauthorized"}, status=403)
            
        settings = store.kitchen_settings
        settings.is_kitchen_paused = not settings.is_kitchen_paused
        settings.save()
        return Response({"paused": settings.is_kitchen_paused})

    @action(detail=True, methods=['get'])
    def reviews(self, request, pk=None):
        store = self.get_object()
        reviews = StoreReview.objects.filter(store=store).order_by('-created_at')
        
        # Calculate rating stats on database level (highly efficient)
        from django.db.models import Avg, Count
        stats = reviews.aggregate(
            avg_rating=Avg('rating'),
            total=Count('id')
        )
        avg_rating = round(stats['avg_rating'], 1) if stats['avg_rating'] is not None else None
        total_reviews = stats['total']
        
        # Calculate star counts
        star_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        counts_query = reviews.values('rating').annotate(count=Count('id'))
        for item in counts_query:
            r = item['rating']
            if 1 <= r <= 5:
                star_counts[r] = item['count']

        from rest_framework.pagination import PageNumberPagination
        class StoreReviewPagination(PageNumberPagination):
            page_size = 5
            page_size_query_param = 'page_size'
            max_page_size = 50

        paginator = StoreReviewPagination()
        page = paginator.paginate_queryset(reviews, request)
        if page is not None:
            serializer = StoreReviewSerializer(page, many=True)
            return Response({
                'count': paginator.page.paginator.count,
                'next': paginator.get_next_link(),
                'previous': paginator.get_previous_link(),
                'results': serializer.data,
                'avg_rating': avg_rating,
                'star_counts': star_counts
            })

        serializer = StoreReviewSerializer(reviews, many=True)
        return Response({
            'count': total_reviews,
            'next': None,
            'previous': None,
            'results': serializer.data,
            'avg_rating': avg_rating,
            'star_counts': star_counts
        })

class SystemSupportConfigViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def list(self, request):
        config = SystemSupportConfig.get_solo()
        serializer = SystemSupportConfigSerializer(config, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['post', 'put', 'patch'], permission_classes=[permissions.IsAuthenticated])
    def update_config(self, request):
        if request.user.role != 'SUPERUSER' and not request.user.is_superuser:
            return Response({"error": "Permission denied. Only Superusers can update support configuration."}, status=403)
        config = SystemSupportConfig.get_solo()
        serializer = SystemSupportConfigSerializer(config, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
