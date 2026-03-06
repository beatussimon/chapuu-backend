from django.db import models
from django.conf import settings
from stores.models import Store, Table

class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        ACTIVE = 'ACTIVE', 'Active (Seated)'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        NO_SHOW = 'NO_SHOW', 'No Show'

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='reservations')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reservations')
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservations')
    
    reservation_time = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    guest_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Res: {self.customer.username} at {self.store.name} on {self.reservation_time}"

class TableSession(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='sessions')
    table = models.ForeignKey(Table, on_delete=models.SET_NULL, null=True, related_name='sessions')
    reservation = models.OneToOneField(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name='session')
    
    is_active = models.BooleanField(default=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Session at Table {self.table.number} ({'Active' if self.is_active else 'Closed'})"
