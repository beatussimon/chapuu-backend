from rest_framework import serializers
from billing.models import CommissionLedgerEntry, MonthlyInvoice, CommissionPayment, PlatformPaymentMethod

class CommissionLedgerEntrySerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    order_id = serializers.IntegerField(source='order.id', read_only=True)

    class Meta:
        model = CommissionLedgerEntry
        fields = ['id', 'order', 'order_id', 'store', 'store_name', 'order_amount', 'commission_rate', 'commission_amount', 'entry_type', 'created_at']
        read_only_fields = ['id', 'order', 'store', 'order_amount', 'commission_rate', 'commission_amount', 'entry_type', 'created_at']

class MonthlyInvoiceSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = MonthlyInvoice
        fields = ['id', 'store', 'store_name', 'year', 'month', 'total_order_amount', 'total_commission', 'order_count', 'status', 'due_date', 'created_at']
        read_only_fields = ['id', 'store', 'year', 'month', 'total_order_amount', 'total_commission', 'order_count', 'due_date', 'created_at']

class CommissionPaymentSerializer(serializers.ModelSerializer):
    submitted_by_username = serializers.CharField(source='submitted_by.username', read_only=True)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True)

    class Meta:
        model = CommissionPayment
        fields = [
            'id', 'invoice', 'amount', 'transaction_id', 'receipt_screenshot', 'status', 
            'rejection_reason', 'submitted_by', 'submitted_by_username', 'submitted_at', 
            'reviewed_by', 'reviewed_by_username', 'reviewed_at'
        ]
        read_only_fields = ['id', 'status', 'rejection_reason', 'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at']

class PlatformPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformPaymentMethod
        fields = ['id', 'provider', 'account_name', 'account_number', 'instructions', 'is_active']
