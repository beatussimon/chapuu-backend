from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'role', 'phone_number', 'employed_store', 'loyalty_points', 
                  'first_name', 'last_name', 'email', 'accepted_liability_policy', 'policy_accepted_at')
        read_only_fields = ('loyalty_points', 'policy_accepted_at')

    def validate(self, attrs):
        # Enforce required fields strictly on creation (Signup)
        if not self.instance:
            required_fields = {
                'first_name': "First name is required.",
                'last_name': "Last name is required.",
                'email': "Email address is required.",
                'phone_number': "Phone number is required.",
                'password': "Password is required.",
                'accepted_liability_policy': "You must accept the Terms & Conditions and Liability Policy to register."
            }
            errors = {}
            for field, message in required_fields.items():
                val = attrs.get(field)
                if val is None or val == '' or (field == 'accepted_liability_policy' and val is not True):
                    errors[field] = message
            
            if errors:
                raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

class StaffSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    
    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'first_name', 'last_name', 'role', 'phone_number', 'is_active', 'employed_store')
        read_only_fields = ('employed_store',)

    def validate_role(self, value):
        if value not in ['CHEF', 'ACCOUNTANT', 'DELIVERY']:
            raise serializers.ValidationError("Only staff roles (CHEF, ACCOUNTANT, DELIVERY) can be managed here.")
        return value

    def create(self, validated_data):
        # Store is assigned in the ViewSet based on the Seller's owned store
        password = validated_data.pop('password', None)
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
        else:
            # Default password if not provided
            user.set_password("Chapuu123!")
        user.save()
        return user
