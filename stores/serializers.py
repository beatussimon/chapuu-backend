from rest_framework import serializers
from stores.models import Store, KitchenSettings, Advertisement, CurrencyConfig, Table

class KitchenSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = KitchenSettings
        fields = '__all__'

class StoreSerializer(serializers.ModelSerializer):
    kitchen_settings = KitchenSettingsSerializer(read_only=True)
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Store
        fields = '__all__'

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
