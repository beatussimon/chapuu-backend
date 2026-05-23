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

    def get_readonly_fields(self, request, obj=None):
        if not request.user.is_superuser:
            # Regular admin cannot modify system-critical permissions and roles
            return self.readonly_fields + ('role', 'is_superuser', 'is_staff', 'user_permissions', 'groups')
        return self.readonly_fields

    def has_change_permission(self, request, obj=None):
        if obj and not request.user.is_superuser:
            # Regular ADMIN cannot change SUPERUSER or other ADMIN accounts in Django Admin
            if obj.is_superuser or obj.role in ['ADMIN', 'SUPERUSER']:
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and not request.user.is_superuser:
            # Regular ADMIN cannot delete SUPERUSER or other ADMIN accounts in Django Admin
            if obj.is_superuser or obj.role in ['ADMIN', 'SUPERUSER']:
                return False
        return super().has_delete_permission(request, obj)

admin.site.register(User, CustomUserAdmin)

