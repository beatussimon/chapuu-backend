from rest_framework import serializers
from stores.models import Store, KitchenSettings, Advertisement, CurrencyConfig, Table, Notice, StorePaymentMethod, SystemSupportConfig

class KitchenSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = KitchenSettings
        fields = '__all__'

class StorePaymentMethodSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = StorePaymentMethod
        fields = '__all__'

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
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Store
        fields = [
            'id', 'owner', 'name', 'store_type', 'location', 'contact_phone', 
            'contact_email', 'image', 'image_url', 'is_active', 'is_open', 
            'base_delivery_fee', 'created_at', 'kitchen_settings', 'payment_methods'
        ]

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

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

