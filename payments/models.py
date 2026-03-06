from django.db import models
from orders.models import Order
from reservations.models import Reservation

class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        SUCCESS = 'SUCCESS', 'Success'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='TZS') # Defaulting to TZS for Zenopay context
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    
    provider_transaction_id = models.CharField(max_length=255, blank=True, null=True)
    provider_receipt_url = models.URLField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment {self.id} - {self.status} - {self.amount} {self.currency}"

class Refund(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='refunds')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    is_successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Refund for Payment {self.payment.id} - {self.amount}"
