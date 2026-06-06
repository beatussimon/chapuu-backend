from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        SELLER = 'SELLER', 'Seller'
        ADMIN = 'ADMIN', 'Admin'
        SUPERUSER = 'SUPERUSER', 'Superuser'
        CHAPUUSTAFF = 'CHAPUUSTAFF', 'Chapuu Staff'
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

    # Saved/Favorited stores
    favorite_stores = models.ManyToManyField('stores.Store', related_name='favorited_by', blank=True)

    def save(self, *args, **kwargs):
        from django.utils import timezone
        if self.is_superuser or self.role == self.Role.SUPERUSER:
            self.role = self.Role.SUPERUSER
            self.is_superuser = True
            self.is_staff = True
        elif self.role in [self.Role.ADMIN, self.Role.CHAPUUSTAFF]:
            self.is_staff = True
            
        if self.accepted_liability_policy and not self.policy_accepted_at:
            self.policy_accepted_at = timezone.now()
            
        if self.profile_picture and hasattr(self.profile_picture, 'file'):
            from django.core.files.uploadedfile import UploadedFile
            if isinstance(self.profile_picture.file, UploadedFile):
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

class PushDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_devices')
    push_token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=20, blank=True, null=True) # e.g. 'ios', 'android'
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.platform} ({self.push_token[:10]}...)"

