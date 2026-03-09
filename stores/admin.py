from django.contrib import admin
from stores.models import Store, KitchenSettings, Table, Advertisement, CurrencyConfig

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'store_type', 'is_active', 'created_at')
    list_filter = ('store_type', 'is_active')
    search_fields = ('name', 'owner__username')

@admin.register(KitchenSettings)
class KitchenSettingsAdmin(admin.ModelAdmin):
    list_display = ('store', 'max_concurrent_prep_slots', 'is_kitchen_paused', 'auto_approve_orders')

@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ('number', 'store', 'capacity', 'is_active')
    list_filter = ('store', 'is_active')

@admin.register(Advertisement)
class AdvertisementAdmin(admin.ModelAdmin):
    list_display = ('title', 'store', 'is_active', 'created_at')

@admin.register(CurrencyConfig)
class CurrencyConfigAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'symbol', 'rate_to_base', 'is_default', 'is_active')
