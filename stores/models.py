from django.db import models
from django.conf import settings
from config.image_utils import compress_image

class Store(models.Model):
    class StoreType(models.TextChoices):
        RESTAURANT = 'RESTAURANT', 'Restaurant'
        SHOP = 'SHOP', 'Shop'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stores')
    name = models.CharField(max_length=255)
    store_type = models.CharField(max_length=20, choices=StoreType.choices, default=StoreType.RESTAURANT)
    location = models.TextField()
    contact_phone = models.CharField(max_length=50, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    image = models.ImageField(upload_to='stores/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_open = models.BooleanField(default=True, help_text="Store open/closed status toggle.")
    base_delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Auto-compress store image to WebP on upload
        if self.image and hasattr(self.image, 'file'):
            try:
                compressed = compress_image(self.image)
                if compressed and compressed is not self.image:
                    self.image = compressed
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.store_type})"

class StorePaymentMethod(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='payment_methods')
    provider = models.CharField(max_length=100, help_text="e.g. M-Pesa, Bank Transfer, Cash")
    account_name = models.CharField(max_length=255, blank=True, null=True)
    account_number = models.CharField(max_length=100, blank=True, null=True)
    instructions = models.TextField(blank=True, null=True, help_text="e.g. Send to Till Number 123456")
    image = models.ImageField(upload_to='payment_methods/', null=True, blank=True, help_text="Network logo/image")
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.image and hasattr(self.image, 'file'):
            try:
                compressed = compress_image(self.image)
                if compressed and compressed is not self.image:
                    self.image = compressed
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.provider} for {self.store.name}"

class KitchenSettings(models.Model):
    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name='kitchen_settings')
    max_concurrent_prep_slots = models.PositiveIntegerField(default=10)
    is_kitchen_paused = models.BooleanField(default=False)
    auto_approve_orders = models.BooleanField(default=True)

    def __str__(self):
        return f"Kitchen Settings for {self.store.name}"

class Table(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='tables')
    number = models.CharField(max_length=10)
    capacity = models.PositiveIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Table {self.number} at {self.store.name}"

class Advertisement(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True, related_name='ads', help_text="Null means global admin ad.")
    title = models.CharField(max_length=255)
    media = models.FileField(upload_to='ads/', help_text="Image or Video for the TV dashboard")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ad: {self.title} (Store: {self.store.name if self.store else 'GLOBAL'})"

class CurrencyConfig(models.Model):
    """
    Stores available currencies and their exchange rates relative to
    the base currency (TZS). To add a new currency, just insert a row.
    """
    code = models.CharField(max_length=10, unique=True, help_text="e.g. TZS, USD, KES")
    name = models.CharField(max_length=50, help_text="e.g. Tanzanian Shilling")
    symbol = models.CharField(max_length=10, help_text="e.g. TSh, $, KSh")
    rate_to_base = models.DecimalField(
        max_digits=14, decimal_places=6, default=1.0,
        help_text="How many units of the base currency (TZS) equal 1 unit of this currency. TZS=1.0, USD≈2500."
    )
    is_default = models.BooleanField(default=False, help_text="The primary display currency.")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Currency Configs"

    def __str__(self):
        return f"{self.code} ({self.symbol}) — rate {self.rate_to_base}"

    @classmethod
    def convert(cls, amount, from_code, to_code):
        """Convert amount between two currencies via the base (TZS) with caching."""
        if from_code == to_code:
            return amount
            
        from django.core.cache import cache
        
        # Cache both currency rates for 1 hour
        from_rate = cache.get(f'currency_rate_{from_code}')
        if from_rate is None:
            from_curr = cls.objects.get(code=from_code)
            from_rate = from_curr.rate_to_base
            cache.set(f'currency_rate_{from_code}', from_rate, 3600)
            
        to_rate = cache.get(f'currency_rate_{to_code}')
        if to_rate is None:
            to_curr = cls.objects.get(code=to_code)
            to_rate = to_curr.rate_to_base
            cache.set(f'currency_rate_{to_code}', to_rate, 3600)

        # amount in base = amount * from_rate, then divide by to_rate
        base_amount = amount * from_rate
        return base_amount / to_rate

class Notice(models.Model):
    title = models.CharField(max_length=255)
    message = models.TextField()
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True, related_name='notices', help_text="If null, it's a global notice.")
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='notices_received', help_text="If null, goes to all staff in the store/global.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notices_sent')
    read_by = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='read_notices', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notice: {self.title}"
