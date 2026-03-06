from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'role', 'phone_number', 'employed_store', 'loyalty_points')
        read_only_fields = ('loyalty_points',)

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            role=validated_data.get('role', 'CUSTOMER'),
            phone_number=validated_data.get('phone_number', ''),
            employed_store=validated_data.get('employed_store', None)
        )
        return user
