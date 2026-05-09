from django.db import models
from orders.models import Order
from reservations.models import Reservation

class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING  = 'PENDING',  'Pending'
        VERIFIED = 'VERIFIED', 'Verified'    # Accountant confirmed offline receipt
        WAIVED   = 'WAIVED',   'Waived'      # Walk-in: collected in person, no digital proof
        FAILED   = 'FAILED',   'Failed'      # Rejected or expired
        REFUNDED = 'REFUNDED', 'Refunded'

    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    order       = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    amount      = models.DecimalField(max_digits=10, decimal_places=2)
    currency    = models.CharField(max_length=3, default='TZS')
    status      = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_method = models.ForeignKey(
        'stores.StorePaymentMethod',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="Which offline payment method the customer used"
    )
    notes = models.TextField(blank=True, null=True, help_text="Accountant notes or walk-in payment details")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    def __str__(self):
        target = f"Order #{self.order_id}" if self.order_id else f"Reservation #{self.reservation_id}"
        return f"Payment {self.id} — {self.status} — {self.amount} {self.currency} ({target})"

class Refund(models.Model):
    payment    = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='refunds')
    amount     = models.DecimalField(max_digits=10, decimal_places=2)
    reason     = models.TextField()
    is_successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Refund for Payment {self.payment.id} — {self.amount}"
