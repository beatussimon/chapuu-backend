from rest_framework import serializers
from reviews.models import StoreReview

class StoreReviewSerializer(serializers.ModelSerializer):
    customer_username = serializers.SerializerMethodField()
    items_reviewed = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    delivery_location = serializers.SerializerMethodField()
    fulfillment_mode = serializers.SerializerMethodField()

    class Meta:
        model = StoreReview
        fields = ['id', 'store', 'customer', 'customer_username', 'order', 'items_reviewed', 'customer_phone', 'delivery_location', 'fulfillment_mode', 'rating', 'comment', 'created_at']
        read_only_fields = ['customer', 'created_at']

    def validate_comment(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Comment text is required when leaving a review.")
        return value

    def get_customer_username(self, obj):
        try:
            if obj.customer:
                return obj.customer.username
        except Exception:
            pass
        return "Anonymous"

    def get_items_reviewed(self, obj):
        try:
            if obj.order:
                return [item.product.name for item in obj.order.items.all()]
        except Exception:
            pass
        return []

    def get_customer_phone(self, obj):
        try:
            if obj.order:
                return obj.order.customer_phone
        except Exception:
            pass
        return None

    def get_delivery_location(self, obj):
        try:
            if obj.order:
                return obj.order.delivery_location
        except Exception:
            pass
        return None

    def get_fulfillment_mode(self, obj):
        try:
            if obj.order:
                return obj.order.fulfillment_mode
        except Exception:
            pass
        return None

