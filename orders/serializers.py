from rest_framework import serializers
from orders.models import Order, OrderItem
from catalog.serializers import ProductSerializer
from payments.models import Payment

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'quantity', 'unit_price', 'is_ready']
        read_only_fields = ['is_ready', 'unit_price']

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
    reservation_status = serializers.SerializerMethodField()
    reservation_guest_count = serializers.SerializerMethodField()
    has_review = serializers.SerializerMethodField()
    review_details = serializers.SerializerMethodField()
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_phone = serializers.CharField(source='store.contact_phone', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'store', 'store_name', 'store_phone', 'customer', 'customer_name', 'table', 'table_number', 'reservation', 'reservation_time', 'reservation_status', 'reservation_guest_count', 'state', 
            'fulfillment_mode', 'customer_phone', 'delivery_location', 'total_amount', 'delivery_fee', 'created_at', 
            'updated_at', 'scheduled_time', 'is_instant_payment', 'items', 'payment_message', 'payment_receipt', 'has_review', 'review_details',
            'delivery_code', 'delivery_code_attempts', 'prep_time_option', 'scheduled_start_time', 
            'reschedule_requested_time', 'reschedule_requested_start_time', 'reschedule_status'
        ]
        read_only_fields = [
            'state', 'total_amount', 'customer', 'created_at', 'updated_at', 
            'delivery_code', 'delivery_code_attempts', 'reschedule_status'
        ]

    def get_has_review(self, obj):
        return hasattr(obj, 'review')

    def get_reservation_time(self, obj):
        if obj.reservation:
            return obj.reservation.reservation_time
        return None

    def get_reservation_status(self, obj):
        if obj.reservation:
            return obj.reservation.status
        return None

    def get_reservation_guest_count(self, obj):
        if obj.reservation:
            return obj.reservation.guest_count
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
        payment_message = data.get('payment_message', '').strip() if data.get('payment_message') else ''

        # Transaction ID / Proof of Payment is mandatory for non-instant payments
        if not is_instant and not payment_message:
            raise serializers.ValidationError({
                "payment_message": "Transaction ID or proof of payment is required."
            })
        
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

        # Scheduling validations
        from django.utils import timezone
        scheduled_time = data.get('scheduled_time')
        prep_option = data.get('prep_time_option', 'DYNAMIC')
        scheduled_start_time = data.get('scheduled_start_time')

        if scheduled_time:
            if scheduled_time <= timezone.now():
                raise serializers.ValidationError({"scheduled_time": "Scheduled time must be in the future."})

            if prep_option == 'CUSTOM':
                if not scheduled_start_time:
                    raise serializers.ValidationError({"scheduled_start_time": "Scheduled start time is required for Custom prep option."})
                if scheduled_start_time <= timezone.now():
                    raise serializers.ValidationError({"scheduled_start_time": "Scheduled start time must be in the future."})
                if scheduled_start_time >= scheduled_time:
                    raise serializers.ValidationError({"scheduled_start_time": "Scheduled start time must be before the scheduled delivery/pickup time."})
            
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        
        # Stock validation & Price snapshotting
        from catalog.models import InventoryStock
        from datetime import timedelta
        
        processed_items = []
        total = 0
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
            
            # Query db product directly to bypass any user-submitted unit_price values
            catalog_price = product.price
            item_data['unit_price'] = catalog_price
            total += catalog_price * quantity
            processed_items.append(item_data)
        
        # Set calculated scheduled_start_time dynamically using historical averages
        scheduled_time = validated_data.get('scheduled_time')
        prep_option = validated_data.get('prep_time_option', 'DYNAMIC')
        if scheduled_time:
            if prep_option == 'DYNAMIC':
                max_prep = max((i['product'].get_average_prep_time() for i in processed_items), default=0)
                validated_data['scheduled_start_time'] = scheduled_time - timedelta(minutes=max_prep)
            else:
                # For CUSTOM option, use submitted scheduled_start_time (already validated)
                pass

        order = Order.objects.create(total_amount=total, **validated_data)
        
        for item_data in processed_items:
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
