from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from catalog.models import Category
from stores.models import Store

User = get_user_model()

class UniversalCategoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='test_seller', password='password', role='SELLER')
        self.client.force_authenticate(user=self.user)
        self.store = Store.objects.create(name='Test Store', owner=self.user)

    def test_create_category_duplicate_prevention(self):
        # Create category 1: 'Beverages'
        res1 = self.client.post('/api/categories/', {'name': 'Beverages'})
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Category.objects.count(), 1)
        self.assertIsNone(Category.objects.first().store)

        # Create category 2: 'beverages' (lowercase duplicate)
        res2 = self.client.post('/api/categories/', {'name': 'beverages'})
        self.assertEqual(res2.status_code, status.HTTP_200_OK) # Returns 200 OK for existing
        self.assertEqual(Category.objects.count(), 1) # Count remains 1!

        # Create category 3: 'BEVERAGES' (uppercase duplicate)
        res3 = self.client.post('/api/categories/', {'name': 'BEVERAGES'})
        self.assertEqual(res3.status_code, status.HTTP_200_OK)
        self.assertEqual(Category.objects.count(), 1) # Count remains 1!

        # Create category 4: 'Pizza' (different category)
        res4 = self.client.post('/api/categories/', {'name': 'Pizza'})
        self.assertEqual(res4.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Category.objects.count(), 2)
