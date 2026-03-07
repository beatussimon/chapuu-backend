from rest_framework import serializers
from reviews.models import StoreReview

class StoreReviewSerializer(serializers.ModelSerializer):
    customer_username = serializers.CharField(source='customer.username', read_only=True)
    items_reviewed = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    delivery_location = serializers.SerializerMethodField()
    fulfillment_mode = serializers.SerializerMethodField()

    class Meta:
        model = StoreReview
        fields = ['id', 'store', 'customer', 'customer_username', 'order', 'items_reviewed', 'customer_phone', 'delivery_location', 'fulfillment_mode', 'rating', 'comment', 'created_at']
        read_only_fields = ['customer', 'created_at']

    def get_items_reviewed(self, obj):
        if obj.order:
            return [item.product.name for item in obj.order.items.all()]
        return []

    def get_customer_phone(self, obj):
        if obj.order:
            return obj.order.customer_phone
        return None

    def get_delivery_location(self, obj):
        if obj.order:
            return obj.order.delivery_location
        return None

    def get_fulfillment_mode(self, obj):
        if obj.order:
            return obj.order.fulfillment_mode
        return None
