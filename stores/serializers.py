from rest_framework import serializers
from stores.models import Store, KitchenSettings, Advertisement, CurrencyConfig, Table, Notice, StorePaymentMethod, SystemSupportConfig, StoreGalleryImage, GlobalPaymentMethod, SellerApplication, ApplicationDocument
from django.contrib.auth import get_user_model

User = get_user_model()

class KitchenSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = KitchenSettings
        fields = '__all__'

class GlobalPaymentMethodSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = GlobalPaymentMethod
        fields = ['id', 'name', 'logo', 'logo_url', 'requires_account_details', 'is_active']

    def get_logo_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        return None

class StorePaymentMethodSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    global_payment_method_detail = GlobalPaymentMethodSerializer(source='global_payment_method', read_only=True)

    class Meta:
        model = StorePaymentMethod
        fields = '__all__'
        extra_kwargs = {
            'provider': {'required': False}
        }

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        elif obj.global_payment_method and obj.global_payment_method.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.global_payment_method.logo.url)
            return obj.global_payment_method.logo.url
        return None

    def validate(self, attrs):
        global_pm = attrs.get('global_payment_method')
        
        if not global_pm and not attrs.get('provider'):
            raise serializers.ValidationError({"provider": "This field is required."})

        # If there's a global payment method, validate account details based on its config
        if global_pm:
            # Sync legacy provider field
            attrs['provider'] = global_pm.name
            
            # Sync legacy image if global logo exists and not overriding locally
            if global_pm.logo and not attrs.get('image'):
                attrs['image'] = global_pm.logo

            if global_pm.requires_account_details:
                account_name = attrs.get('account_name')
                account_number = attrs.get('account_number')
                
                errs = {}
                if not account_name or not str(account_name).strip():
                    errs["account_name"] = "Account Name is required for this payment method."
                if not account_number or not str(account_number).strip():
                    errs["account_number"] = "Account Number is required for this payment method."
                if errs:
                    raise serializers.ValidationError(errs)
            else:
                # If account details are not required (e.g. Cash), nullify them or set to empty
                attrs['account_name'] = ""
                attrs['account_number'] = ""
        else:
            # Fallback legacy validation: if provider contains "mpesa" or "bank"
            provider = attrs.get('provider', '')
            if provider and any(keyword in provider.lower() for keyword in ['m-pesa', 'mpesa', 'bank', 'transfer', 'tigo', 'airtel', 'halo']):
                account_name = attrs.get('account_name')
                account_number = attrs.get('account_number')
                
                errs = {}
                if not account_name or not str(account_name).strip():
                    errs["account_name"] = "Account Name is required for mobile money or bank transfers."
                if not account_number or not str(account_number).strip():
                    errs["account_number"] = "Account Number is required for mobile money or bank transfers."
                if errs:
                    raise serializers.ValidationError(errs)

        return attrs

class StoreGalleryImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = StoreGalleryImage
        fields = ['id', 'store', 'image', 'image_url', 'caption', 'created_at']

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

class StoreSerializer(serializers.ModelSerializer):
    kitchen_settings = KitchenSettingsSerializer(read_only=True)
    payment_methods = StorePaymentMethodSerializer(many=True, read_only=True)
    gallery_images = StoreGalleryImageSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    avg_rating = serializers.SerializerMethodField()
    
    class Meta:
        model = Store
        fields = [
            'id', 'owner', 'name', 'store_type', 'location', 'latitude', 'longitude', 'directions', 'requires_table_for_dine_in', 'contact_phone', 
            'contact_email', 'image', 'image_url', 'is_active', 'is_open', 'working_hours', 
            'base_delivery_fee', 'created_at', 'free_trial_start', 'free_trial_end', 'kitchen_settings', 'payment_methods',
            'gallery_images', 'distance_km', 'review_count', 'avg_rating'
        ]

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_distance_km(self, obj):
        return getattr(obj, 'distance_km', None)

    def get_review_count(self, obj):
        return obj.reviews.count()

    def get_avg_rating(self, obj):
        from django.db.models import Avg
        avg = obj.reviews.aggregate(Avg('rating'))['rating__avg']
        if avg is not None:
            return round(avg, 1)
        return None

    def validate(self, attrs):
        request = self.context.get('request')
        user = request.user if request else None
        
        # Check if this is an update to an existing store
        if self.instance and user:
            # Check if user is a regular seller (not admin or superuser)
            is_admin_or_su = user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser
            if not is_admin_or_su:
                # Detect if the store has coordinates already registered
                has_registered_coords = (self.instance.latitude is not None and self.instance.latitude != '') and \
                                         (self.instance.longitude is not None and self.instance.longitude != '')
                
                # Check if coordinates or geocoded address text are attempting to be modified
                lat_changing = 'latitude' in attrs and attrs['latitude'] != self.instance.latitude
                lng_changing = 'longitude' in attrs and attrs['longitude'] != self.instance.longitude
                loc_changing = 'location' in attrs and attrs['location'] != self.instance.location
                
                if has_registered_coords and (lat_changing or lng_changing or loc_changing):
                    raise serializers.ValidationError({
                        "latitude": "Store location coordinates are already registered and locked. Please contact support to request updates."
                    })
            
            # Prevent non-superusers from modifying free trial fields
            is_superuser = user.role == 'SUPERUSER' or user.is_superuser
            if not is_superuser:
                trial_start_changing = 'free_trial_start' in attrs and attrs['free_trial_start'] != self.instance.free_trial_start
                trial_end_changing = 'free_trial_end' in attrs and attrs['free_trial_end'] != self.instance.free_trial_end
                if trial_start_changing or trial_end_changing:
                    raise serializers.ValidationError({
                        "free_trial_start": "Only SUPERUSER accounts can modify free trial periods."
                    })
        return attrs

class TableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        fields = ['id', 'store', 'number', 'capacity', 'is_active']

class AdvertisementSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    class Meta:
        model = Advertisement
        fields = '__all__'

class CurrencyConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurrencyConfig
        fields = ['id', 'code', 'name', 'symbol', 'rate_to_base', 'is_default', 'is_active']

class NoticeSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notice
        fields = ['id', 'title', 'message', 'store', 'target_user', 'created_by', 'created_by_username', 'is_read', 'created_at']
        read_only_fields = ['created_by']

    def get_is_read(self, obj):
        user = self.context.get('request').user
        if user.is_authenticated:
            return obj.read_by.filter(id=user.id).exists()
        return False

class SystemSupportConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSupportConfig
        fields = '__all__'

class ApplicantLookupSerializer(serializers.ModelSerializer):
    has_active_application = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'phone_number', 'role', 'has_active_application']

    def get_has_active_application(self, obj):
        return obj.seller_applications.filter(status__in=['AWAITING_SIGNATURE', 'PENDING_REVIEW', 'UNDER_REVIEW']).exists()

class ApplicationDocumentSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationDocument
        fields = ['id', 'image', 'image_url', 'caption', 'uploaded_at']

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

class SellerApplicationSerializer(serializers.ModelSerializer):
    venue_photos = ApplicationDocumentSerializer(many=True, read_only=True)
    applicant_username = serializers.CharField(source='applicant.username', read_only=True)
    applicant_name = serializers.SerializerMethodField()
    submitted_by_username = serializers.CharField(source='submitted_by.username', read_only=True)

    class Meta:
        model = SellerApplication
        fields = '__all__'
        read_only_fields = ['status', 'reviewed_by', 'admin_notes', 'rejection_reason', 'created_store', 'digital_signature', 'signed_at']

    def get_applicant_name(self, obj):
        return f"{obj.applicant.first_name} {obj.applicant.last_name}".strip()

class SellerApplicationListSerializer(serializers.ModelSerializer):
    applicant_username = serializers.CharField(source='applicant.username', read_only=True)
    applicant_name = serializers.SerializerMethodField()
    submitted_by_username = serializers.CharField(source='submitted_by.username', read_only=True)
    venue_photos_count = serializers.SerializerMethodField()

    class Meta:
        model = SellerApplication
        fields = [
            'id', 'applicant_username', 'applicant_name', 'store_name', 'store_type', 
            'status', 'submitted_by_username', 'created_at', 'updated_at', 
            'venue_photos_count', 'contact_phone', 'contact_email', 'location', 
            'digital_signature', 'venue_photos', 'estimated_customer_base', 
            'service_quality_rating', 'staff_notes', 'trial_period_days'
        ]
    
    venue_photos = ApplicationDocumentSerializer(many=True, read_only=True)

    def get_applicant_name(self, obj):
        return f"{obj.applicant.first_name} {obj.applicant.last_name}".strip()

    def get_venue_photos_count(self, obj):
        return obj.venue_photos.count()

class CustomerApplicationStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = SellerApplication
        fields = ['id', 'store_name', 'store_type', 'location', 'status', 'rejection_reason', 'created_at', 'updated_at', 'digital_signature']
        read_only_fields = fields

