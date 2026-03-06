from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        SELLER = 'SELLER', 'Seller'
        ADMIN = 'ADMIN', 'Admin'
        CHEF = 'CHEF', 'Chef'
        DELIVERY = 'DELIVERY', 'Delivery Driver'
    
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    loyalty_points = models.PositiveIntegerField(default=0)
    
    # Optional link to a specific store for staff roles (CHEF, DELIVERY)
    employed_store = models.ForeignKey('stores.Store', on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')

    def __str__(self):
        return f"{self.username} ({self.role})"

