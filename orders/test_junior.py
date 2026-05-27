from django.test import TestCase
from users.models import User
from stores.models import Store
from orders.models import Order
from rest_framework.test import APIClient
from django.urls import reverse

class OrderVisibilityTest(TestCase):
    def test_seller1_visibility(self):
        # Setup
        seller1 = User.objects.create_user(username='seller1', password='pw', role='SELLER')
        store1 = Store.objects.create(name='Main Store', owner=seller1)
        
        seller2 = User.objects.create_user(username='seller2', password='pw', role='SELLER')
        store2 = Store.objects.create(name='JUICE TAMU', owner=seller2)
        
        junior = User.objects.create_user(username='junior', password='pw', role='CUSTOMER')
        
        order28 = Order.objects.create(
            store=store2, customer=junior, total_amount=100.0, 
            state=Order.State.AWAITING_PAYMENT, fulfillment_mode='TAKEAWAY'
        )
        
        # Test if seller2 sees it
        client = APIClient()
        client.force_authenticate(user=seller2)
        res = client.get(reverse('order-list') + '?no_pagination=true&exclude_inactive=true&store=' + str(store2.id))
        
        print("SELLER2 ORDERS:", len(res.data))
        if res.data:
            print("ORDER ID:", res.data[0]['id'])
        
        seller1.employed_store = store2
        seller1.save()
        
        client.force_authenticate(user=seller1)
        res1 = client.get(reverse('order-list') + '?no_pagination=true&exclude_inactive=true&store=' + str(store2.id))
        print("SELLER1 ORDERS:", len(res1.data))
        self.assertEqual(len(res1.data), 1)

