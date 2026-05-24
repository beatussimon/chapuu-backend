from rest_framework import viewsets, permissions, generics, status, views
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model
from users.serializers import UserSerializer, StaffSerializer
from stores.models import Store

User = get_user_model()

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.role in ['ADMIN', 'SUPERUSER'] or request.user.is_superuser))

class IsSeller(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'SELLER')

class StaffManagementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Sellers to manage their store staff.
    """
    serializer_class = StaffSerializer
    permission_classes = [IsSeller | IsAdminUser]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return User.objects.filter(role__in=['CHEF', 'ACCOUNTANT', 'DELIVERY'])
        # Sellers only see staff belonging to their owned stores
        owned_stores = Store.objects.filter(owner=user)
        return User.objects.filter(employed_store__in=owned_stores)

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == 'ADMIN':
            # Admin must specify employed_store in request data
            serializer.save()
        else:
            # Seller: automatically link to their first owned store
            # In a multi-store setup, we'd use a query param or header
            store = Store.objects.filter(owner=user).first()
            if not store:
                from rest_framework.exceptions import ValidationError
                raise ValidationError("You must own a store to hire staff.")
            serializer.save(employed_store=store)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        staff = self.get_object()
        staff.is_active = False
        staff.save()
        
        # Blacklist all refresh tokens for this user
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        tokens = OutstandingToken.objects.filter(user=staff)
        for token in tokens:
            BlacklistedToken.objects.get_or_create(token=token)
            
        return Response({"status": "Staff deactivated and sessions terminated."})

    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        staff = self.get_object()
        staff.is_active = True
        staff.save()
        return Response({"status": "Staff reactivated and re-hired successfully."})

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        staff = self.get_object()
        new_password = request.data.get('password')
        if not new_password:
             return Response({"error": "New password required"}, status=status.HTTP_400_BAD_REQUEST)
        staff.set_password(new_password)
        staff.save()
        return Response({"status": "Password reset successfully."})

class UserViewSet(viewsets.ModelViewSet):
    """
    CRUD for users. Restricted strictly to ADMINs.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if (instance.role == User.Role.SUPERUSER or instance.is_superuser) and not (request.user.role == User.Role.SUPERUSER or request.user.is_superuser):
            return Response(
                {"detail": "Only the Platform Owner (Superuser) can delete Superuser accounts."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)


class CustomerRegistrationView(generics.CreateAPIView):
    """
    Public registration endpoint strictly for new CUSTOMER roles.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        # Force the role to CUSTOMER regardless of what is passed in the payload
        data = request.data.copy()
        data['role'] = 'CUSTOMER'
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

class CurrentUserView(views.APIView):
    """
    Endpoint to get current authenticated user's profile details.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
