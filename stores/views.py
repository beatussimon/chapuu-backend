from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from stores.models import Store, KitchenSettings, Advertisement, CurrencyConfig, Table, Notice, StorePaymentMethod, SystemSupportConfig, StoreGalleryImage, GlobalPaymentMethod, SellerApplication, ApplicationDocument
from stores.serializers import StoreSerializer, KitchenSettingsSerializer, AdvertisementSerializer, CurrencyConfigSerializer, TableSerializer, NoticeSerializer, StorePaymentMethodSerializer, SystemSupportConfigSerializer, StoreGalleryImageSerializer, GlobalPaymentMethodSerializer, SellerApplicationSerializer, SellerApplicationListSerializer, ApplicantLookupSerializer, CustomerApplicationStatusSerializer, ApplicationDocumentSerializer
from users.permissions import IsChapuuStaffOrAdmin
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction

User = get_user_model()
from stores.services import KitchenEngine
from reviews.models import StoreReview
from reviews.serializers import StoreReviewSerializer
from config.pagination import LargePagination, StandardPagination

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
    pagination_class = None

class IsSellerOrAdminForWriteStore(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and (request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER'] or request.user.is_superuser)

class StorePaymentMethodViewSet(viewsets.ModelViewSet):
    serializer_class = StorePaymentMethodSerializer
    permission_classes = [IsSellerOrAdminForWriteStore]
    pagination_class = None

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
    pagination_class = None

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
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        from django.db.models import Q
        
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return Notice.objects.all()
            
        # 1. Truly Global: No store, no specific target
        global_notices = Q(store__isnull=True, target_user__isnull=True)
        # 2. Specifically Targeted: Explicitly for this user
        targeted_notices = Q(target_user=user)
        
        if user.role == 'SELLER':
            # 3. Store Broadcast: For all staff in the owner's store
            store_notices = Q(store__owner=user, target_user__isnull=True)
            return Notice.objects.filter(global_notices | targeted_notices | store_notices).exclude(cleared_by=user)
            
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY']:
            store = user.employed_store
            if store:
                store_notices = Q(store=store, target_user__isnull=True)
                return Notice.objects.filter(global_notices | targeted_notices | store_notices).exclude(cleared_by=user)
            else:
                return Notice.objects.filter(global_notices | targeted_notices).exclude(cleared_by=user)
        
        # Customers/Other only see global or specific targets
        return Notice.objects.filter(global_notices | targeted_notices).exclude(cleared_by=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        notice = self.get_object()
        user = request.user
        
        # Admins have the power to actually permanently delete notices
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return super().destroy(request, *args, **kwargs)
            
        # For everyone else, "Deleting" simply adds them to `cleared_by`
        notice.cleared_by.add(user)
        return Response(status=status.HTTP_204_NO_CONTENT)

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
    pagination_class = None

class TableViewSet(viewsets.ModelViewSet):
    """CRUD for tables. Read-only for customers, full CRUD for sellers/admins."""
    serializer_class = TableSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = None

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
    pagination_class = None

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
    pagination_class = LargePagination

    def get_queryset(self):
        user = self.request.user
        if user and user.is_authenticated and (user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser):
            return Store.objects.all().prefetch_related('payment_methods', 'kitchen_settings')
        return Store.objects.filter(is_active=True).prefetch_related('payment_methods', 'kitchen_settings')
    
    def list(self, request, *args, **kwargs):
        # Intelligent Caching for the main store list (no filters/params)
        # This drastically reduces DB load for the 'Browse' page
        if not request.query_params:
            cache_key = "all_stores_list_page_1"
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
            response = self.get_paginated_response(serializer.data)
            if not request.query_params:
                cache.set("all_stores_list_page_1", response.data, 60*60) # Cache for 1 hour
            return response

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    
    def retrieve(self, request, *args, **kwargs):
        # Surgical Caching for specific store profiles
        cache_key = f"store_detail_{kwargs.get('pk')}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)
            
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        
        # Cache for 24 hours (cleared by signals on update)
        cache.set(cache_key, serializer.data, 60*60*24)
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
            
        # 4. Fallback for staff with no employed_store (Return 404 to avoid data leak)
        if not store and user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY']:
            return Response({"error": "You are not currently linked to any store. Please contact an administrator."}, status=404)
            
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
        counts_query = reviews.order_by().values('rating').annotate(count=Count('id'))
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

class SellerApplicationViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return SellerApplication.objects.all()
        elif user.role == 'CHAPUUSTAFF':
            return SellerApplication.objects.filter(submitted_by=user)
        return SellerApplication.objects.filter(applicant=user)

    def get_serializer_class(self):
        if self.action == 'list':
            return SellerApplicationListSerializer
        return SellerApplicationSerializer

    def perform_create(self, serializer):
        user = self.request.user
        if user.role not in ['CHAPUUSTAFF', 'ADMIN', 'SUPERUSER'] and not user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only Chapuu Staff and Admins can submit applications.")
            
        applicant = serializer.validated_data.get('applicant')
        if applicant.role == 'SELLER':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("This user is already a seller.")
            
        if SellerApplication.objects.filter(applicant=applicant, status__in=['AWAITING_SIGNATURE', 'PENDING_REVIEW', 'UNDER_REVIEW']).exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError("This user already has an active application.")
            
        serializer.save(submitted_by=user, status='AWAITING_SIGNATURE')

    def perform_update(self, serializer):
        instance = serializer.instance
        user = self.request.user
        if user.role == 'CHAPUUSTAFF':
            if instance.submitted_by != user:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You can only edit your own submissions.")
            if instance.status != 'REJECTED':
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Only rejected applications can be edited and re-submitted.")
            serializer.save(status='AWAITING_SIGNATURE', rejection_reason='')
        else:
            serializer.save()

    @action(detail=False, methods=['get'], permission_classes=[IsChapuuStaffOrAdmin])
    def lookup_user(self, request):
        username = request.query_params.get('q')
        if not username:
            return Response({"error": "Username is required"}, status=400)
        try:
            user = User.objects.get(username=username)
            serializer = ApplicantLookupSerializer(user)
            return Response(serializer.data)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

    @action(detail=False, methods=['get'])
    def my_application(self, request):
        user = request.user
        if user.role == 'SELLER':
            # Optionally show approved application
            app = SellerApplication.objects.filter(applicant=user, status='APPROVED').order_by('-created_at').first()
        else:
            app = SellerApplication.objects.filter(applicant=user).order_by('-created_at').first()
            
        if not app:
            return Response({"error": "No application found"}, status=404)
        serializer = CustomerApplicationStatusSerializer(app)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        app = self.get_object()
        if request.user != app.applicant:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only sign your own application.")
            
        if app.status != 'AWAITING_SIGNATURE':
            return Response({"error": "Application is not awaiting signature."}, status=400)
            
        signature = request.data.get('digital_signature')
        if not signature:
            return Response({"error": "Digital signature is required."}, status=400)
            
        app.digital_signature = signature
        app.signed_at = timezone.now()
        app.status = 'PENDING_REVIEW'
        app.save(update_fields=['digital_signature', 'signed_at', 'status'])
        
        return Response({"status": "Signed successfully"})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def mark_reviewing(self, request, pk=None):
        app = self.get_object()
        if app.status != 'PENDING_REVIEW':
            return Response({"error": "Application must be PENDING_REVIEW"}, status=400)
        app.status = 'UNDER_REVIEW'
        app.save(update_fields=['status'])
        Notice.objects.create(
            target_user=app.applicant,
            created_by=request.user,
            title='Your Seller Application is Under Review',
            message=f'Our team is currently reviewing your application for {app.store_name}.'
        )
        return Response({"status": "Marked under review"})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def reject(self, request, pk=None):
        app = self.get_object()
        if app.status in ['APPROVED', 'REJECTED']:
            return Response({"error": "Application is already decided"}, status=400)
            
        reason = request.data.get('rejection_reason', 'No reason provided.')
        app.status = 'REJECTED'
        app.rejection_reason = reason
        app.reviewed_by = request.user
        app.save(update_fields=['status', 'rejection_reason', 'reviewed_by'])
        
        Notice.objects.create(
            target_user=app.applicant,
            created_by=request.user,
            title='Seller Application Action Required',
            message=f'Your application for {app.store_name} needs corrections. Reason: {reason}'
        )
        return Response({"status": "Rejected"})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    @transaction.atomic
    def approve(self, request, pk=None):
        app = self.get_object()
        if app.status == 'APPROVED':
            return Response({"error": "Already approved"}, status=400)
        if not app.digital_signature:
            return Response({"error": "Cannot approve without digital signature"}, status=400)
            
        store = Store.objects.create(
            owner=app.applicant,
            name=app.store_name,
            store_type=app.store_type,
            location=app.location,
            latitude=app.latitude,
            longitude=app.longitude,
            directions=app.directions,
            contact_phone=app.contact_phone,
            contact_email=app.contact_email,
            is_active=True,
            free_trial_start=timezone.now() if app.trial_period_days > 0 else None,
            free_trial_end=timezone.now() + timedelta(days=app.trial_period_days) if app.trial_period_days > 0 else None
        )
        
        first_photo = app.venue_photos.first()
        if first_photo:
            store.image = first_photo.image
            store.save(update_fields=['image'])
            
        applicant = app.applicant
        if applicant.role == 'CUSTOMER':
            applicant.role = 'SELLER'
            applicant.save(update_fields=['role'])
            
        app.status = 'APPROVED'
        app.reviewed_by = request.user
        app.created_store = store
        app.save(update_fields=['status', 'reviewed_by', 'created_store'])
        
        Notice.objects.create(
            target_user=applicant,
            created_by=request.user,
            store=store,
            title='🎉 Your Seller Application Has Been Approved!',
            message=f'Congratulations! Your store "{store.name}" is now live on Chapuu. Log in to access your Seller Dashboard.'
        )
        
        return Response({"status": "approved", "store_id": store.id})

    @action(detail=True, methods=['post'], permission_classes=[IsChapuuStaffOrAdmin])
    def upload_photos(self, request, pk=None):
        app = self.get_object()
        user = request.user
        if user.role == 'CHAPUUSTAFF' and app.submitted_by != user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only upload photos for your own submissions.")
            
        if app.venue_photos.count() >= 5:
            return Response({"error": "Maximum 5 venue photos allowed"}, status=400)
            
        image = request.FILES.get('image')
        caption = request.data.get('caption', '')
        if not image:
            return Response({"error": "Image file is required"}, status=400)
            
        doc = ApplicationDocument.objects.create(application=app, image=image, caption=caption)
        serializer = ApplicationDocumentSerializer(doc, context={'request': request})
        return Response(serializer.data, status=201)

    @action(detail=True, methods=['delete'], url_path='delete-photo/(?P<photo_id>[^/.]+)', permission_classes=[IsChapuuStaffOrAdmin])
    def delete_photo(self, request, photo_id, pk=None):
        app = self.get_object()
        user = request.user
        if user.role == 'CHAPUUSTAFF' and app.submitted_by != user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only delete photos for your own submissions.")
            
        try:
            doc = ApplicationDocument.objects.get(id=photo_id, application=app)
            doc.delete()
            return Response({"status": "deleted"}, status=204)
        except ApplicationDocument.DoesNotExist:
            return Response({"error": "Photo not found"}, status=404)
