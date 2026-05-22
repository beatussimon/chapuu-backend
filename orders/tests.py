from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User
from stores.models import Store
from catalog.models import Product
from orders.models import Order

class POSFlowTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='seller', password='password123', role='SELLER'
        )
        self.client.force_authenticate(user=self.seller)
        
        self.store = Store.objects.create(
            name='Test Shop',
            owner=self.seller,
            store_type='SHOP'
        )
        
        self.product = Product.objects.create(
            name='Test Product',
            price=10.0,
            store=self.store
        )

    def test_shop_pos_order_fixed_flow(self):
        """
        Verify the fixed POS flow for a SHOP:
        1. Create order (backend moves it to READY)
        2. Frontend checks state and skips redundant advance_state calls.
        """
        url = reverse('order-list')
        payload = {
            'store': self.store.id,
            'fulfillment_mode': 'TAKEAWAY',
            'is_instant_payment': True,
            'items': [
                {'product': self.product.id, 'quantity': 1, 'unit_price': 10.0}
            ]
        }
        
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['state'], Order.State.READY)
        
        # Frontend logic (fixed):
        if response.data['state'] not in [Order.State.READY, Order.State.COMPLETED]:
            # This part should NOT be executed for SHOP instant orders
            advance_url = reverse('order-advance-state', kwargs={'pk': response.data['id']})
            self.client.post(advance_url, {'state': 'PREPARING'}, format='json')
            self.client.post(advance_url, {'state': 'READY'}, format='json')

        order = Order.objects.get(id=response.data['id'])
        self.assertEqual(order.state, Order.State.READY)

    def test_restaurant_pos_order_flow(self):
        """
        Verify POS flow for a RESTAURANT:
        1. Create order (backend moves it to QUEUED)
        2. Frontend advances it to PREPARING then READY (if posSkipKitchen is true)
        """
        self.store.store_type = 'RESTAURANT'
        self.store.save()
        
        url = reverse('order-list')
        payload = {
            'store': self.store.id,
            'fulfillment_mode': 'TAKEAWAY',
            'is_instant_payment': True,
            'items': [
                {'product': self.product.id, 'quantity': 1, 'unit_price': 10.0}
            ]
        }
        
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['state'], Order.State.QUEUED)
        
        order_id = response.data['id']
        advance_url = reverse('order-advance-state', kwargs={'pk': order_id})
        
        # Advance to PREPARING
        res1 = self.client.post(advance_url, {'state': 'PREPARING'}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        
        # Advance to READY
        res2 = self.client.post(advance_url, {'state': 'READY'}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        
        order = Order.objects.get(id=order_id)
        self.assertEqual(order.state, Order.State.READY)

    def test_order_advance_permissions(self):
        """
        Test that only authorized roles can advance state.
        """
        # Ensure it's a RESTAURANT so it doesn't auto-advance to READY from PAID
        self.store.store_type = 'RESTAURANT'
        self.store.save()

        # Create a customer user
        customer = User.objects.create_user(username='customer', password='password123', role='CUSTOMER')
        
        # Create an order
        order = Order.objects.create(
            store=self.store,
            customer=customer,
            total_amount=10.0,
            state=Order.State.AWAITING_PAYMENT
        )
        
        advance_url = reverse('order-advance-state', kwargs={'pk': order.id})
        
        # 1. Customer tries to mark as PAID (Should fail)
        self.client.force_authenticate(user=customer)
        response = self.client.post(advance_url, {'state': 'PAID'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # 2. Seller tries to mark as PAID (Should succeed)
        self.client.force_authenticate(user=self.seller)
        response = self.client.post(advance_url, {'state': 'PAID'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertEqual(order.state, Order.State.PAID)

class ReservationLinkageTest(TestCase):
    def setUp(self):
        from reservations.models import Reservation
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='seller2', password='password123', role='SELLER'
        )
        self.customer = User.objects.create_user(
            username='customer2', password='password123', role='CUSTOMER'
        )
        self.client.force_authenticate(user=self.customer)
        
        self.store = Store.objects.create(
            name='Pizza Palace',
            owner=self.seller,
            store_type='RESTAURANT'
        )
        
        self.product = Product.objects.create(
            name='Test Product',
            price=10.0,
            store=self.store
        )
        
        from django.utils import timezone
        import datetime
        self.reservation = Reservation.objects.create(
            store=self.store,
            customer=self.customer,
            reservation_time=timezone.now() + datetime.timedelta(days=1),
            duration_minutes=60,
            guest_count=2,
            status=Reservation.Status.PENDING
        )

    def test_reservation_pre_order_links_payment_and_confirms(self):
        """
        Verify that placing a reservation pre-order:
        1. Links the payment's reservation FK.
        2. Transitioning order state to PAID via Seller/Accountant auto-confirms the reservation.
        """
        from reservations.models import Reservation
        from payments.models import Payment

        url = reverse('order-list')
        payload = {
            'store': self.store.id,
            'fulfillment_mode': 'RESERVATION',
            'reservation': self.reservation.id,
            'payment_message': 'MPESA transaction slip 123',
            'items': [
                {'product': self.product.id, 'quantity': 1}
            ]
        }
        
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order_id = response.data['id']
        
        # 1. Payment created should have reservation linked
        payment = Payment.objects.filter(order_id=order_id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.reservation_id, self.reservation.id)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        
        # 2. Advance state to PAID (using seller credentials)
        self.client.force_authenticate(user=self.seller)
        advance_url = reverse('order-advance-state', kwargs={'pk': order_id})
        response = self.client.post(advance_url, {'state': 'PAID'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify payment is verified and reservation is confirmed
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.VERIFIED)
        
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.CONFIRMED)
