from rest_framework import serializers
from reservations.models import Reservation, TableSession

class ReservationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.username', read_only=True)
    table_number = serializers.CharField(source='table.number', read_only=True)
    session_started_at = serializers.SerializerMethodField()
    
    class Meta:
        model = Reservation
        fields = [
            'id', 'store', 'customer', 'customer_name', 'table', 'table_number', 
            'reservation_time', 'duration_minutes', 'guest_count', 
            'status', 'deposit_amount', 'created_at', 'session_started_at'
        ]
        read_only_fields = ['customer', 'status', 'deposit_amount', 'created_at']

    def get_session_started_at(self, obj):
        session = getattr(obj, 'session', None)
        if session and session.is_active:
            return session.started_at
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
