from rest_framework import serializers
from reservations.models import Reservation, TableSession

class ReservationOrderSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    state = serializers.CharField(read_only=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    items = serializers.SerializerMethodField()
    
    def get_items(self, obj):
        return [
            {
                "id": item.id,
                "product_id": item.product.id,
                "product_name": item.product.name,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price)
            }
            for item in obj.items.all()
        ]

class ReservationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.username', read_only=True)
    table_number = serializers.CharField(source='table.number', read_only=True)
    session_id = serializers.SerializerMethodField()
    session_started_at = serializers.SerializerMethodField()
    can_modify = serializers.SerializerMethodField()
    linked_order = serializers.SerializerMethodField()
    
    class Meta:
        model = Reservation
        fields = [
            'id', 'store', 'customer', 'customer_name', 'table', 'table_number', 
            'reservation_time', 'duration_minutes', 'guest_count', 
            'status', 'deposit_amount', 'created_at', 'session_id', 'session_started_at', 'can_modify',
            'linked_order'
        ]
        read_only_fields = ['customer', 'status', 'deposit_amount', 'created_at']

    def get_linked_order(self, obj):
        linked_order = getattr(obj, 'linked_order', None)
        if linked_order:
            return ReservationOrderSerializer(linked_order).data
        return None

    def get_can_modify(self, obj):
        from django.utils import timezone
        import datetime
        # Policy: Cannot modify within 2 hours of arrival
        now = timezone.now()
        threshold = obj.reservation_time - datetime.timedelta(hours=2)
        
        if now > threshold:
            return False
            
        # Also cannot modify if status is not PENDING or CONFIRMED
        if obj.status not in [Reservation.Status.PENDING, Reservation.Status.CONFIRMED]:
            return False
            
        # Check linked order (if food is already PREPARING, it's too late)
        linked_order = getattr(obj, 'linked_order', None)
        if linked_order and linked_order.state not in ['CREATED', 'AWAITING_PAYMENT', 'PAID', 'QUEUED']:
            return False
            
        return True

    def get_session_started_at(self, obj):
        session = getattr(obj, 'session', None)
        if session and session.is_active:
            return session.started_at
        return None

    def get_session_id(self, obj):
        session = getattr(obj, 'session', None)
        if session and session.is_active:
            return session.id
        return None

class TableSessionSerializer(serializers.ModelSerializer):
    table_number = serializers.CharField(source='table.number', read_only=True)
    
    class Meta:
        model = TableSession
        fields = [
            'id', 'store', 'table', 'table_number', 'reservation', 
            'is_active', 'started_at', 'ended_at'
        ]
        read_only_fields = ['store', 'table', 'reservation', 'started_at']
