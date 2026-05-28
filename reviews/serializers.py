from rest_framework import serializers
from reviews.models import StoreReview

class StoreReviewSerializer(serializers.ModelSerializer):
    customer_username = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    customer_profile_picture = serializers.SerializerMethodField()
    items_reviewed = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    delivery_location = serializers.SerializerMethodField()
    fulfillment_mode = serializers.SerializerMethodField()

    class Meta:
        model = StoreReview
        fields = ['id', 'store', 'customer', 'customer_username', 'customer_name', 'customer_profile_picture', 'order', 'items_reviewed', 'customer_phone', 'delivery_location', 'fulfillment_mode', 'rating', 'comment', 'created_at']
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

    def get_customer_name(self, obj):
        try:
            if obj.customer:
                full_name = f"{obj.customer.first_name} {obj.customer.last_name}".strip()
                return full_name if full_name else obj.customer.username
        except Exception:
            pass
        return "Anonymous"

    def get_customer_profile_picture(self, obj):
        try:
            if obj.customer and obj.customer.profile_picture:
                request = self.context.get('request')
                if request is not None:
                    return request.build_absolute_uri(obj.customer.profile_picture.url)
                return obj.customer.profile_picture.url
        except Exception:
            pass
        return None

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

