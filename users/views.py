from rest_framework import viewsets, permissions, generics, status, views
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from users.serializers import UserSerializer

User = get_user_model()

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'ADMIN')

class UserViewSet(viewsets.ModelViewSet):
    """
    CRUD for users. Restricted strictly to ADMINs.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]

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
