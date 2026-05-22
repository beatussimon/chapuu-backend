from django.contrib import admin
from orders.models import Order, OrderItem, OrderEventLog

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

class OrderEventLogInline(admin.TabularInline):
    model = OrderEventLog
    extra = 0
    readonly_fields = ('created_at',)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'store', 'customer', 'state', 'fulfillment_mode', 'total_amount', 'is_locked', 'is_suspicious', 'created_at')
    list_filter = ('state', 'fulfillment_mode', 'store', 'is_locked', 'is_suspicious')
    search_fields = ('id', 'customer__username', 'customer_phone')
    inlines = [OrderItemInline, OrderEventLogInline]
