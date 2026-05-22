from django.test import TestCase
from django.contrib.auth import get_user_model
from stores.models import Store
from reviews.serializers import StoreReviewSerializer

User = get_user_model()

class StoreReviewSerializerTestCase(TestCase):
    def setUp(self):
        # Create user and store for testing
        self.owner = User.objects.create_user(username='owner', password='password123')
        self.customer = User.objects.create_user(username='customer', password='password123')
        self.store = Store.objects.create(
            owner=self.owner,
            name="Test Restaurant",
            location="Test Location",
            store_type="RESTAURANT"
        )

    def test_valid_review_serializer(self):
        # Valid review comment and rating
        data = {
            'store': self.store.id,
            'rating': 5,
            'comment': "Excellent food and service!"
        }
        serializer = StoreReviewSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['comment'], "Excellent food and service!")

    def test_missing_comment_fails(self):
        # Empty comment should raise ValidationError
        data = {
            'store': self.store.id,
            'rating': 4,
            'comment': ""
        }
        serializer = StoreReviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('comment', serializer.errors)
        self.assertEqual(str(serializer.errors['comment'][0]), "Comment text is required when leaving a review.")

    def test_whitespace_only_comment_fails(self):
        # Whitespace-only comment should raise ValidationError
        data = {
            'store': self.store.id,
            'rating': 3,
            'comment': "    "
        }
        serializer = StoreReviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('comment', serializer.errors)
        self.assertEqual(str(serializer.errors['comment'][0]), "Comment text is required when leaving a review.")
