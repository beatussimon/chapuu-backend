from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from stores.models import Store, KitchenSettings, Advertisement, CurrencyConfig, Table
from stores.serializers import StoreSerializer, KitchenSettingsSerializer, AdvertisementSerializer, CurrencyConfigSerializer, TableSerializer
from stores.services import KitchenEngine
from reviews.models import StoreReview
from reviews.serializers import StoreReviewSerializer

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
    queryset = Store.objects.filter(is_active=True)
    serializer_class = StoreSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print("STORE CREATION VALIDATION ERROR:", serializer.errors)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)
    
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
