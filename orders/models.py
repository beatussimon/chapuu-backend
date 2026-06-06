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
        OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY', 'Out for Delivery'
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
    
    state = models.CharField(max_length=20, choices=State.choices, default=State.CREATED, db_index=True)
    fulfillment_mode = models.CharField(max_length=20, choices=FulfillmentMode.choices)
    
    customer_phone = models.CharField(max_length=50, blank=True, null=True)
    delivery_location = models.TextField(blank=True, null=True)
    delivery_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Customer's GPS latitude captured at checkout")
    delivery_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Customer's GPS longitude captured at checkout")
    delivery_directions = models.TextField(blank=True, null=True,
        help_text="Specific landmarks or detailed directions for delivery rider")

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, help_text="Amount discounted at POS")
    pos_custom_items = models.JSONField(blank=True, null=True, help_text="JSON list of non-catalog custom items added at POS")
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, help_text="Delivery or pickup fee set by seller/accountant.")
    delivery_fee_status = models.CharField(
        max_length=20,
        choices=[('PENDING', 'Pending'), ('AGREED', 'Agreed'), ('RENEGOTIATE', 'Renegotiate')],
        default='PENDING',
        help_text="Fulfillment delivery fee negotiation status"
    )


    
    payment_message = models.TextField(blank=True, null=True, help_text="User's text transaction slip or confirmation ID.")
    payment_receipt = models.ImageField(upload_to='receipts/', blank=True, null=True, help_text="User's uploaded receipt image.")
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)

    # Handoff codes
    delivery_code = models.CharField(max_length=6, blank=True, null=True, help_text="6-digit verification code")
    delivery_code_attempts = models.PositiveIntegerField(default=0, help_text="Verification attempts count")
    is_locked = models.BooleanField(default=False, help_text="Locked due to exceeding maximum verification attempts.")
    is_suspicious = models.BooleanField(default=False, help_text="Flagged as suspicious due to failed verification attempts.")

    # Scheduled order preparation controls
    prep_time_option = models.CharField(
        max_length=15,
        choices=[('DYNAMIC', 'Dynamic (System-Calculated)'), ('CUSTOM', 'Custom Start Time')],
        default='DYNAMIC'
    )
    scheduled_start_time = models.DateTimeField(null=True, blank=True, help_text="When prep should begin")

    # Reschedule request tracking
    reschedule_requested_time = models.DateTimeField(null=True, blank=True, help_text="Requested scheduled_time")
    reschedule_requested_start_time = models.DateTimeField(null=True, blank=True, help_text="Requested prep start time")
    reschedule_status = models.CharField(
        max_length=20,
        choices=[('PENDING', 'Pending Approval'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')],
        null=True, blank=True
    )
    reschedule_rejection_reason = models.TextField(blank=True, null=True, help_text="Reason why the reschedule request was rejected")
    reschedule_count = models.PositiveIntegerField(default=0, help_text="Number of times this order has been successfully rescheduled")
    reschedule_request_count = models.PositiveIntegerField(default=0, help_text="Number of reschedule requests submitted by the customer")

    is_instant_payment = models.BooleanField(
        default=False,
        help_text=(
            "True when a walk-in customer pays in person at time of order. "
            "Skips AWAITING_PAYMENT state and goes directly to PAID. "
            "Can only be set by store staff (SELLER, ADMIN, ACCOUNTANT, CHEF). "
            "Must NOT be used with DELIVERY fulfillment mode."
        )
    )

    class Meta:
        indexes = [
            models.Index(fields=['store', 'state'], name='order_store_state_idx'),
            models.Index(fields=['store', 'created_at'], name='order_store_created_idx'),
        ]

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
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order #{self.order.id} Event: {self.previous_state} -> {self.new_state}"

class OrderRescheduleRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Approval'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='reschedule_requests')
    requested_time = models.DateTimeField(help_text="Requested scheduled_time")
    requested_start_time = models.DateTimeField(help_text="Requested prep start time")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True, null=True, help_text="Reason for rejection")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reschedule Request for Order #{self.order.id} - {self.status}"
