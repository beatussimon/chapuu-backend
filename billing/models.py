from django.db import models
from django.conf import settings
from decimal import Decimal

class CommissionLedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        COMMISSION = 'COMMISSION', 'Fulfillment Commission (3%)'
        CANCELLATION_FEE = 'CANCELLATION_FEE', 'Scheduled Cancellation Platform Share (3%)'

    order = models.ForeignKey('orders.Order', on_delete=models.PROTECT, related_name='commission_entries')
    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT, related_name='commission_entries')
    order_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'))
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    entry_type = models.CharField(max_length=30, choices=EntryType.choices, default=EntryType.COMMISSION)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.store.name} - {self.entry_type} - {self.commission_amount}"

class MonthlyInvoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PENDING_REVIEW = 'PENDING_REVIEW', 'Pending Review'
        PAID = 'PAID', 'Paid'
        OVERDUE = 'OVERDUE', 'Overdue'

    store = models.ForeignKey('stores.Store', on_delete=models.PROTECT, related_name='invoices')
    year = models.IntegerField()
    month = models.IntegerField()
    total_order_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    total_commission = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    order_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('store', 'year', 'month')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.store.name} Invoice - {self.year}/{self.month:02d} ({self.status})"

class CommissionPayment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    invoice = models.ForeignKey(MonthlyInvoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_id = models.CharField(max_length=255)
    receipt_screenshot = models.ImageField(upload_to='commission_receipts/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.TextField(blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_payments')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.invoice.store.name} Payment - {self.amount} ({self.status})"

class PlatformPaymentMethod(models.Model):
    provider = models.CharField(max_length=100) # e.g. M-Pesa, Bank Transfer
    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=100)
    instructions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.provider} - {self.account_name} ({self.account_number})"
