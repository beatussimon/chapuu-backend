from rest_framework import serializers
from reviews.models import StoreReview

class StoreReviewSerializer(serializers.ModelSerializer):
    customer_username = serializers.CharField(source='customer.username', read_only=True)

    class Meta:
        model = StoreReview
        fields = ['id', 'store', 'customer', 'customer_username', 'rating', 'comment', 'created_at']
        read_only_fields = ['customer', 'created_at']
