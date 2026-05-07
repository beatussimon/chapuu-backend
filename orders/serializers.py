from rest_framework import serializers
from orders.models import Order, OrderItem
from catalog.serializers import ProductSerializer
from payments.models import Payment

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'quantity', 'unit_price', 'is_ready']
        read_only_fields = ['is_ready']

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # Expose product details gracefully for rendering without breaking write validation
        representation['product'] = {
            'id': instance.product.id,
            'name': instance.product.name,
        }
        return representation

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    table_number = serializers.CharField(source='table.number', read_only=True)
    customer_name = serializers.CharField(source='customer.username', read_only=True)
    reservation_time = serializers.SerializerMethodField()
    has_review = serializers.SerializerMethodField()
    review_details = serializers.SerializerMethodField()
    store_name = serializers.CharField(source='store.name', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'store', 'store_name', 'customer', 'customer_name', 'table', 'table_number', 'reservation', 'reservation_time', 'state', 
            'fulfillment_mode', 'customer_phone', 'delivery_location', 'total_amount', 'delivery_fee', 'created_at', 
            'updated_at', 'scheduled_time', 'items', 'payment_message', 'payment_receipt', 'has_review', 'review_details'
        ]
        read_only_fields = ['state', 'total_amount', 'customer', 'created_at', 'updated_at']

    def get_has_review(self, obj):
        return hasattr(obj, 'review')

    def get_reservation_time(self, obj):
        if obj.reservation:
            return obj.reservation.reservation_time
        return None

    def get_review_details(self, obj):
        if hasattr(obj, 'review'):
            return {
                'rating': obj.review.rating,
                'comment': obj.review.comment,
                'created_at': obj.review.created_at
            }
        return None

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        
        # Calculate total amount
        total = sum(item['unit_price'] * item['quantity'] for item in items_data)
        
        order = Order.objects.create(total_amount=total, **validated_data)
        
        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)
            
        Payment.objects.create(
            order=order,
            amount=total,
            status=Payment.Status.PENDING
        )
            
        # If instantly paid (e.g. walk-in POS), enqueue it
        if order.state in [order.State.PAID, order.State.QUEUED]:
            from stores.services import KitchenEngine
            KitchenEngine.enqueue_order(order)

        return order
