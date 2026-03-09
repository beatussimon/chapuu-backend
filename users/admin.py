from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from users.models import User

class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ['username', 'email', 'role', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        ('Role Details', {'fields': ('role', 'phone_number', 'loyalty_points', 'employed_store')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role Details', {'fields': ('role', 'phone_number', 'loyalty_points', 'employed_store')}),
    )

admin.site.register(User, CustomUserAdmin)
