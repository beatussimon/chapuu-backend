from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        SELLER = 'SELLER', 'Seller'
        ADMIN = 'ADMIN', 'Admin'
        SUPERUSER = 'SUPERUSER', 'Superuser'
        CHEF = 'CHEF', 'Chef'
        DELIVERY = 'DELIVERY', 'Delivery Driver'
        ACCOUNTANT = 'ACCOUNTANT', 'Accountant'
    
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    loyalty_points = models.PositiveIntegerField(default=0)
    
    accepted_liability_policy = models.BooleanField(default=False)
    policy_accepted_at = models.DateTimeField(null=True, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', null=True, blank=True)

    # Optional link to a specific store for staff roles (CHEF, DELIVERY)
    employed_store = models.ForeignKey('stores.Store', on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')

    def save(self, *args, **kwargs):
        from django.utils import timezone
        if self.is_superuser or self.role == self.Role.SUPERUSER:
            self.role = self.Role.SUPERUSER
            self.is_superuser = True
            self.is_staff = True
        elif self.role == self.Role.ADMIN:
            self.is_staff = True
            
        if self.accepted_liability_policy and not self.policy_accepted_at:
            self.policy_accepted_at = timezone.now()
            
        if self.profile_picture and hasattr(self.profile_picture, 'file'):
            try:
                from config.image_utils import compress_image
                compressed = compress_image(self.profile_picture)
                if compressed and compressed is not self.profile_picture:
                    self.profile_picture = compressed
            except Exception:
                pass

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.role})"

