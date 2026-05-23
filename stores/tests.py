from django.test import TestCase
from django.contrib.auth import get_user_model
from stores.models import Store, GlobalPaymentMethod, StorePaymentMethod
from stores.serializers import StorePaymentMethodSerializer

User = get_user_model()

class StorePaymentMethodSerializerTests(TestCase):
    def setUp(self):
        # Create a test owner
        self.owner = User.objects.create_user(
            username='testowner',
            password='testpassword',
            role='SELLER'
        )
        # Create a test store
        self.store = Store.objects.create(
            owner=self.owner,
            name='Test Store',
            location='Test Location'
        )
        # Create a template that requires details (e.g. M-Pesa)
        self.mpesa_template = GlobalPaymentMethod.objects.create(
            name='M-Pesa',
            requires_account_details=True,
            is_active=True
        )
        # Create a template that doesn't require details (e.g. Cash)
        self.cash_template = GlobalPaymentMethod.objects.create(
            name='Cash',
            requires_account_details=False,
            is_active=True
        )

    def test_requires_details_validation_success(self):
        """Should validate successfully when details are provided for M-Pesa"""
        data = {
            'store': self.store.id,
            'global_payment_method': self.mpesa_template.id,
            'account_name': 'Jane Doe',
            'account_number': '0712345678',
            'instructions': 'Send money via Lipa na M-Pesa'
        }
        serializer = StorePaymentMethodSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['provider'], 'M-Pesa')
        self.assertEqual(validated_data['account_name'], 'Jane Doe')
        self.assertEqual(validated_data['account_number'], '0712345678')

    def test_requires_details_validation_failure_missing_fields(self):
        """Should fail validation when account name or number is missing for M-Pesa"""
        data = {
            'store': self.store.id,
            'global_payment_method': self.mpesa_template.id,
            'account_name': '',
            'account_number': '',
            'instructions': 'Send money'
        }
        serializer = StorePaymentMethodSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('account_name', serializer.errors)
        self.assertIn('account_number', serializer.errors)

    def test_no_details_required_clears_fields(self):
        """Should validate successfully without details for Cash, and nullify/clear the fields"""
        data = {
            'store': self.store.id,
            'global_payment_method': self.cash_template.id,
            'account_name': 'Should Be Ignored',
            'account_number': '12345',
            'instructions': 'Pay cash at counter'
        }
        serializer = StorePaymentMethodSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        validated_data = serializer.validated_data
        self.assertEqual(validated_data['provider'], 'Cash')
        self.assertEqual(validated_data['account_name'], '')
        self.assertEqual(validated_data['account_number'], '')
