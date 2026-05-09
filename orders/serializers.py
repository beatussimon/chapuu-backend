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
            'updated_at', 'scheduled_time', 'is_instant_payment', 'items', 'payment_message', 'payment_receipt', 'has_review', 'review_details'
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

    def validate(self, data):
        is_instant = data.get('is_instant_payment', False)
        fulfillment_mode = data.get('fulfillment_mode', '')
        
        if is_instant:
            # Cannot pay on spot for a delivery order
            if fulfillment_mode == Order.FulfillmentMode.DELIVERY:
                raise serializers.ValidationError(
                    "Instant payment is not valid for delivery orders. "
                    "The customer has not received the goods yet."
                )
            # Delivery fee must be zero for instant non-delivery orders
            if data.get('delivery_fee', 0) and float(data.get('delivery_fee', 0)) > 0:
                raise serializers.ValidationError(
                    "Delivery fee must be 0 for instant payment walk-in orders."
                )
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        
        # Stock validation
        from catalog.models import InventoryStock
        for item_data in items_data:
            product = item_data['product']
            quantity = item_data['quantity']
            if product.requires_inventory:
                try:
                    stock = InventoryStock.objects.get(product=product)
                    if stock.quantity < quantity:
                        raise serializers.ValidationError(f"Only {stock.quantity} available for {product.name}.")
                except InventoryStock.DoesNotExist:
                    raise serializers.ValidationError(f"Product {product.name} is out of stock.")
        
        # Calculate total
        total = sum(item['unit_price'] * item['quantity'] for item in items_data)
        order = Order.objects.create(total_amount=total, **validated_data)
        
        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)
            # Deduct stock immediately on order creation
            product = item_data['product']
            if product.requires_inventory:
                try:
                    stock = InventoryStock.objects.get(product=product)
                    stock.quantity -= item_data['quantity']
                    stock.save()
                except InventoryStock.DoesNotExist:
                    pass
        
        return order

class PublicOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    class Meta:
        model = OrderItem
        fields = ['product_name', 'quantity']

class PublicOrderSerializer(serializers.ModelSerializer):
    items = PublicOrderItemSerializer(many=True, read_only=True)
    class Meta:
        model = Order
        fields = ['id', 'state', 'fulfillment_mode', 'created_at', 'items']
