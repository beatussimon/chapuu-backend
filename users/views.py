from rest_framework import viewsets, permissions, generics, status, views
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model
from users.serializers import UserSerializer, StaffSerializer
from stores.models import Store
from config.pagination import LargePagination, StandardPagination


User = get_user_model()

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser))

class IsSeller(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'SELLER')

class StaffManagementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Sellers to manage their store staff.
    """
    serializer_class = StaffSerializer
    permission_classes = [IsSeller | IsAdminUser]
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return User.objects.filter(role__in=['CHEF', 'ACCOUNTANT', 'DELIVERY'])
        # Sellers only see staff belonging to their owned stores
        owned_stores = Store.objects.filter(owner=user)
        return User.objects.filter(employed_store__in=owned_stores)

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == 'ADMIN':
            # Admin must specify employed_store in request data
            serializer.save()
        else:
            # Seller: automatically link to their first owned store
            # In a multi-store setup, we'd use a query param or header
            store = Store.objects.filter(owner=user).first()
            if not store:
                from rest_framework.exceptions import ValidationError
                raise ValidationError("You must own a store to hire staff.")
            serializer.save(employed_store=store)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        staff = self.get_object()
        staff.is_active = False
        staff.save()
        
        # Blacklist all refresh tokens for this user
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        tokens = OutstandingToken.objects.filter(user=staff)
        for token in tokens:
            BlacklistedToken.objects.get_or_create(token=token)
            
        return Response({"status": "Staff deactivated and sessions terminated."})

    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        staff = self.get_object()
        staff.is_active = True
        staff.save()
        return Response({"status": "Staff reactivated and re-hired successfully."})

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        staff = self.get_object()
        new_password = request.data.get('password')
        if not new_password:
             return Response({"error": "New password required"}, status=status.HTTP_400_BAD_REQUEST)
        staff.set_password(new_password)
        staff.save()
        return Response({"status": "Password reset successfully."})

class UserViewSet(viewsets.ModelViewSet):
    """
    CRUD for users. Restricted strictly to ADMINs.
    """
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]
    pagination_class = LargePagination

    def get_queryset(self):
        queryset = User.objects.all()
        search = self.request.query_params.get('search')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search)
            )
        return queryset

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if (instance.role == User.Role.SUPERUSER or instance.is_superuser) and not (request.user.role == User.Role.SUPERUSER or request.user.is_superuser):
            return Response(
                {"detail": "Only the Platform Owner (Superuser) can delete Superuser accounts."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)


class CustomerRegistrationView(generics.CreateAPIView):
    """
    Public registration endpoint strictly for new CUSTOMER roles.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        # Force the role to CUSTOMER regardless of what is passed in the payload
        data = request.data.copy()
        data['role'] = 'CUSTOMER'
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

class CurrentUserView(views.APIView):
    """
    Endpoint to get current authenticated user's profile details.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

from users.models import PushDevice

class PushDeviceRegisterView(views.APIView):
    """
    Endpoint to register or deregister Expo push tokens.
    POST /api/auth/devices/ - registers token
    DELETE /api/auth/devices/ - deregisters token
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = request.data.get('push_token')
        platform = request.data.get('platform')

        if not token:
            return Response({'error': 'push_token is required'}, status=status.HTTP_400_BAD_REQUEST)

        device, created = PushDevice.objects.update_or_create(
            push_token=token,
            defaults={'user': request.user, 'platform': platform}
        )
        return Response({'status': 'registered', 'created': created}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        token = request.data.get('push_token')
        if not token:
            return Response({'error': 'push_token is required'}, status=status.HTTP_400_BAD_REQUEST)

        deleted, _ = PushDevice.objects.filter(user=request.user, push_token=token).delete()
        return Response({'status': 'deregistered', 'deleted': deleted}, status=status.HTTP_200_OK)


class UserFavoritesView(views.APIView):
    """
    Endpoint to manage current user's favorite stores.
    GET /api/auth/users/me/favorites/ - List user's favorite stores
    POST /api/auth/users/me/favorites/ - Add store to favorites (body: {"store_id": id})
    DELETE /api/auth/users/me/favorites/ - Remove store from favorites (query param: ?store_id=id)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.core.cache import cache
        import uuid
        from stores.serializers import StoreSerializer
        
        lat = request.query_params.get('lat', '')
        lng = request.query_params.get('lng', '')
        radius = request.query_params.get('radius', '')
        page = request.query_params.get('page', '')
        
        # Get or generate user-specific version key for atomic invalidation
        version = cache.get(f"user_favorites_version_{request.user.id}")
        if version is None:
            version = uuid.uuid4().hex
            cache.set(f"user_favorites_version_{request.user.id}", version, 86400) # cache for 24h
            
        cache_key = f"user_favorites_{request.user.id}_v{version}_{lat}_{lng}_{radius}_{page}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = request.user.favorite_stores.filter(is_active=True).prefetch_related('payment_methods', 'kitchen_settings')
        
        # Proximity radius support if lat/lng are passed (like the other store views)
        if lat and lng:
            from stores.geo_utils import annotate_distances, filter_by_radius
            queryset = annotate_distances(queryset, lat, lng)
            if radius:
                queryset = filter_by_radius(queryset, radius)

        # Standard pagination
        from config.pagination import StandardPagination
        paginator = StandardPagination()
        page_qs = paginator.paginate_queryset(queryset, request, view=self)
        if page_qs is not None:
            serializer = StoreSerializer(page_qs, many=True, context={'request': request})
            response_data = paginator.get_paginated_response(serializer.data).data
            cache.set(cache_key, response_data, 60*15) # Cache for 15 minutes
            return Response(response_data)

        serializer = StoreSerializer(queryset, many=True, context={'request': request})
        cache.set(cache_key, serializer.data, 60*15) # Cache for 15 minutes
        return Response(serializer.data)

    def post(self, request):
        from django.core.cache import cache
        store_id = request.data.get('store_id')
        if not store_id:
            return Response({'error': 'store_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            store = Store.objects.get(id=store_id, is_active=True)
        except Store.DoesNotExist:
            return Response({'error': 'Store not found'}, status=status.HTTP_444_NOT_FOUND if False else status.HTTP_404_NOT_FOUND)
        
        request.user.favorite_stores.add(store)
        cache.delete(f"user_favorites_version_{request.user.id}")
        return Response({'status': 'added', 'store_id': store_id}, status=status.HTTP_200_OK)

    def delete(self, request):
        from django.core.cache import cache
        store_id = request.query_params.get('store_id')
        if not store_id:
            return Response({'error': 'store_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            store = Store.objects.get(id=store_id)
        except Store.DoesNotExist:
            return Response({'error': 'Store not found'}, status=status.HTTP_404_NOT_FOUND)
        
        request.user.favorite_stores.remove(store)
        cache.delete(f"user_favorites_version_{request.user.id}")
        return Response({'status': 'removed', 'store_id': store_id}, status=status.HTTP_200_OK)
