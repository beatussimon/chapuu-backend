from rest_framework import permissions

class IsSuperUser(permissions.BasePermission):
    """
    Grants access strictly to SUPERUSER role or Django's superuser flag.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.role == 'SUPERUSER' or request.user.is_superuser))

class IsPlatformAdmin(permissions.BasePermission):
    """
    Grants access to ADMIN or SUPERUSER roles, or Django's superuser flag.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser))

class IsPlatformAdminOrReadOnly(permissions.BasePermission):
    """
    Grants read-only access to authenticated users, and write access only to Platform Admins or Superusers.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser)


class IsChapuuStaffOrAdmin(permissions.BasePermission):
    """
    Grants access to CHAPUUSTAFF, ADMIN, and SUPERUSER roles.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.role in ['CHAPUUSTAFF', 'ADMIN', 'SUPERUSER'] or request.user.is_superuser))
