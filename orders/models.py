from django.db import models
from django.conf import settings
from stores.models import Store, Table
from catalog.models import Product

class Order(models.Model):
    class State(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        AWAITING_PAYMENT = 'AWAITING_PAYMENT', 'Awaiting Payment'
        PAID = 'PAID', 'Paid'
        QUEUED = 'QUEUED', 'Queued'
        PREPARING = 'PREPARING', 'Preparing'
        READY = 'READY', 'Ready'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        EXPIRED = 'EXPIRED', 'Expired'
        REFUNDED = 'REFUNDED', 'Refunded'

    class FulfillmentMode(models.TextChoices):
        TAKEAWAY = 'TAKEAWAY', 'Takeaway'
        DELIVERY = 'DELIVERY', 'Delivery'
        DINE_IN = 'DINE_IN', 'Dine-In'
        RESERVATION = 'RESERVATION', 'Reservation'
        PICKUP = 'PICKUP', 'Pickup'  # For shops: customer collects from counter

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='orders')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    reservation = models.OneToOneField('reservations.Reservation', on_delete=models.SET_NULL, null=True, blank=True, related_name='linked_order')
    
    state = models.CharField(max_length=20, choices=State.choices, default=State.CREATED)
    fulfillment_mode = models.CharField(max_length=20, choices=FulfillmentMode.choices)
    
    customer_phone = models.CharField(max_length=50, blank=True, null=True)
    delivery_location = models.TextField(blank=True, null=True)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    
    payment_message = models.TextField(blank=True, null=True, help_text="User's text transaction slip or confirmation ID.")
    payment_receipt = models.ImageField(upload_to='receipts/', blank=True, null=True, help_text="User's uploaded receipt image.")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Order #{self.id} for {self.store.name} - {self.state}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Track kitchen status at the item level
    is_ready = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.quantity}x {self.product.name} (Order #{self.order.id})"

class OrderEventLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='event_logs')
    previous_state = models.CharField(max_length=20, blank=True)
    new_state = models.CharField(max_length=20)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order #{self.order.id} Event: {self.previous_state} -> {self.new_state}"
