from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from catalog.models import Category, Product
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


class UniversalSearchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='search_seller', password='password', role='SELLER')
        self.store = Store.objects.create(name='Rose Foods', location='Dar es salaam', owner=self.user, is_active=True)
        self.category = Category.objects.create(name='Rice Dishes')
        self.product = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Wali wa Nazi',
            description='Coconut rice with beans',
            price=2500,
            is_active=True
        )

    def test_universal_search_by_product_name(self):
        # Searching "wali" should return the matching product AND the store selling it
        response = self.client.get('/api/search/', {'q': 'wali', 'type': 'all'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        products = response.data['results']['products']
        stores = response.data['results']['stores']
        
        self.assertTrue(any(p['id'] == self.product.id for p in products))
        self.assertTrue(any(s['id'] == self.store.id for s in stores))

    def test_universal_search_by_category_name(self):
        # Searching "Rice" (matching Category name) should return the product
        response = self.client.get('/api/search/', {'q': 'Rice', 'type': 'products'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        products = response.data['results']['products']
        self.assertTrue(any(p['id'] == self.product.id for p in products))

    def test_store_search_by_product_keyword(self):
        # Searching "wali" on /api/stores/ should return "Rose Foods"
        response = self.client.get('/api/stores/', {'search': 'wali'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results') if 'results' in response.data else response.data
        self.assertTrue(any(s['id'] == self.store.id for s in results))
