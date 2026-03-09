from django.contrib import admin
from reservations.models import Reservation, TableSession

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'store', 'table', 'reservation_time', 'status')
    list_filter = ('status', 'store')
    search_fields = ('customer__username', 'store__name')

@admin.register(TableSession)
class TableSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'table', 'store', 'is_active', 'started_at', 'ended_at')
    list_filter = ('is_active', 'store')
