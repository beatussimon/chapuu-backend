from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from stores.models import Store
from reviews.models import StoreReview
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


class StoreReviewAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(username='owner_api', password='password123', role='SELLER')
        self.customer = User.objects.create_user(username='customer_api', password='password123', role='CUSTOMER')
        self.store = Store.objects.create(
            owner=self.owner,
            name="Pizza Haven",
            location="Dar es Salaam",
            store_type="RESTAURANT"
        )
        # Create reviews with various ratings
        # 5 star: 3 reviews
        # 4 star: 2 reviews
        # 3 star: 1 review
        # 2 star: 0 reviews
        # 1 star: 0 reviews
        StoreReview.objects.create(store=self.store, customer=self.customer, rating=5, comment="Great!")
        StoreReview.objects.create(store=self.store, customer=self.customer, rating=5, comment="Awesome!")
        StoreReview.objects.create(store=self.store, customer=self.customer, rating=5, comment="Delicious!")
        StoreReview.objects.create(store=self.store, customer=self.customer, rating=4, comment="Good.")
        StoreReview.objects.create(store=self.store, customer=self.customer, rating=4, comment="Nice.")
        StoreReview.objects.create(store=self.store, customer=self.customer, rating=3, comment="Average.")

    def test_store_reviews_stats_endpoint(self):
        url = reverse('store-reviews', kwargs={'pk': self.store.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Total counts should be 6
        self.assertEqual(response.data['count'], 6)
        
        # Average rating: (5*3 + 4*2 + 3*1)/6 = (15 + 8 + 3)/6 = 26/6 = 4.333 -> 4.3
        self.assertEqual(response.data['avg_rating'], 4.3)
        
        # Star counts breakdown should be accurate (and not all 1s due to Django Group By bug)
        expected_star_counts = {
            5: 3,
            4: 2,
            3: 1,
            2: 0,
            1: 0
        }
        self.assertEqual(response.data['star_counts'], expected_star_counts)

