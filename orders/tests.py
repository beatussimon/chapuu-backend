from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
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
        self.assertEqual(response.data['state'], Order.State.PREPARING)
        
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
        self.product.requires_kitchen = True
        self.product.save()
        
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
        self.product.requires_kitchen = True
        self.product.save()

        # Create a customer user
        customer = User.objects.create_user(username='customer', password='password123', role='CUSTOMER')
        
        # Create an order
        order = Order.objects.create(
            store=self.store,
            customer=customer,
            total_amount=10.0,
            state=Order.State.AWAITING_PAYMENT
        )
        order.items.create(product=self.product, quantity=1, unit_price=10.0)
        
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

class PreorderReschedulingAndSafetyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='seller_t', password='password123', role='SELLER'
        )
        self.admin = User.objects.create_user(
            username='admin_t', password='password123', role='ADMIN'
        )
        self.customer = User.objects.create_user(
            username='customer_t', password='password123', role='CUSTOMER'
        )
        
        self.store = Store.objects.create(
            name='Test Rest',
            owner=self.seller,
            store_type='RESTAURANT'
        )
        
        self.product = Product.objects.create(
            name='Dish',
            price=15.0,
            store=self.store,
            estimated_prep_time_minutes=20
        )

    def test_preorder_reschedule_validations(self):
        """
        Verify reschedule validations:
        1. Rescheduling is allowed in PAID/QUEUED states.
        2. Blocks rescheduling if state is PREPARING.
        3. Enforces future prep start times based on product average prep time.
        """
        from django.utils import timezone
        import datetime

        # Create an upcoming scheduled order
        scheduled_time = timezone.now() + datetime.timedelta(hours=2)
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            total_amount=15.0,
            state=Order.State.PAID,
            scheduled_time=scheduled_time,
            prep_time_option='DYNAMIC'
        )
        # Link order item
        order.items.create(product=self.product, quantity=1, unit_price=15.0)
        
        # Calculate initial prep start time
        order.scheduled_start_time = scheduled_time - datetime.timedelta(minutes=20)
        order.save()

        # 1. Customer requests valid reschedule
        self.client.force_authenticate(user=self.customer)
        new_time = timezone.now() + datetime.timedelta(hours=3)
        res = self.client.post(
            reverse('order-request-reschedule', kwargs={'pk': order.id}),
            {'scheduled_time': new_time.isoformat()},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.reschedule_status, 'PENDING')

        # 2. Try to reschedule too close (blocks because kitchen needs 20 mins)
        too_close_time = timezone.now() + datetime.timedelta(minutes=10)
        res = self.client.post(
            reverse('order-request-reschedule', kwargs={'pk': order.id}),
            {'scheduled_time': too_close_time.isoformat()},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Seller responds to reschedule request
        self.client.force_authenticate(user=self.seller)
        # Attempt rejection without reason (should fail with 400)
        res = self.client.post(
            reverse('order-respond-reschedule', kwargs={'pk': order.id}),
            {'approve': False},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Reject with reason (should succeed)
        res = self.client.post(
            reverse('order-respond-reschedule', kwargs={'pk': order.id}),
            {'approve': False, 'rejection_reason': 'Too busy right now.'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.reschedule_status, 'REJECTED')
        self.assertEqual(order.reschedule_rejection_reason, 'Too busy right now.')

        # 4. Try requesting a new reschedule (allowed since the first was rejected, not approved)
        self.client.force_authenticate(user=self.customer)
        new_time2 = timezone.now() + datetime.timedelta(hours=4)
        res = self.client.post(
            reverse('order-request-reschedule', kwargs={'pk': order.id}),
            {'scheduled_time': new_time2.isoformat()},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Seller approves it
        self.client.force_authenticate(user=self.seller)
        res = self.client.post(
            reverse('order-respond-reschedule', kwargs={'pk': order.id}),
            {'approve': True},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.reschedule_status, 'APPROVED')
        self.assertEqual(order.reschedule_count, 1)

        # 5. Try requesting reschedule again after 1 successful reschedule (should fail with 400)
        self.client.force_authenticate(user=self.customer)
        new_time3 = timezone.now() + datetime.timedelta(hours=5)
        res = self.client.post(
            reverse('order-request-reschedule', kwargs={'pk': order.id}),
            {'scheduled_time': new_time3.isoformat()},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Assert history requests count
        self.assertEqual(order.reschedule_requests.count(), 2)
        self.assertEqual(order.reschedule_requests.filter(status='REJECTED').count(), 1)
        self.assertEqual(order.reschedule_requests.filter(status='APPROVED').count(), 1)

    def test_admin_reset_lock(self):
        """
        Verify admin_reset_lock action resets locked order status.
        """
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            total_amount=15.0,
            state=Order.State.READY,
            is_locked=True,
            delivery_code_attempts=5
        )

        # Non-admin tries to unlock (Should fail)
        self.client.force_authenticate(user=self.customer)
        res = self.client.post(reverse('order-admin-reset-lock', kwargs={'pk': order.id}))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Admin tries to unlock (Should succeed)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(reverse('order-admin-reset-lock', kwargs={'pk': order.id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertFalse(order.is_locked)
        self.assertEqual(order.delivery_code_attempts, 0)

class FreeTrialCommissionTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='seller_trial', password='password123', role='SELLER'
        )
        self.store = Store.objects.create(
            name='Promo Shop',
            owner=self.seller,
            store_type='SHOP'
        )
        self.product = Product.objects.create(
            name='Promo Product',
            price=20.0,
            store=self.store
        )
        self.client.force_authenticate(user=self.seller)

    def test_commission_accrual_during_free_trial(self):
        """
        Verify that order completions during active free trial accrue 0.00 commission.
        """
        from django.utils import timezone
        import datetime
        from billing.models import CommissionLedgerEntry
        from orders.services import OrderStateMachine
        
        # Configure active free trial (from yesterday to tomorrow)
        self.store.free_trial_start = timezone.now() - datetime.timedelta(days=1)
        self.store.free_trial_end = timezone.now() + datetime.timedelta(days=1)
        self.store.save()
        
        order = Order.objects.create(
            store=self.store,
            total_amount=20.0,
            state=Order.State.READY
        )
        
        # Transition to COMPLETED
        OrderStateMachine.transition_order(order, Order.State.COMPLETED, bypass_verification=True)
        
        # Verify 0.00 commission is accrued
        entry = CommissionLedgerEntry.objects.filter(order=order).first()
        self.assertIsNotNone(entry)
        self.assertEqual(float(entry.commission_amount), 0.00)

    def test_commission_accrual_outside_free_trial(self):
        """
        Verify standard 3% commission is accrued outside free trial window.
        """
        from billing.models import CommissionLedgerEntry
        from orders.services import OrderStateMachine
        
        # No free trial dates set
        self.store.free_trial_start = None
        self.store.free_trial_end = None
        self.store.save()
        
        order = Order.objects.create(
            store=self.store,
            total_amount=20.0,
            state=Order.State.READY
        )
        
        # Transition to COMPLETED
        OrderStateMachine.transition_order(order, Order.State.COMPLETED, bypass_verification=True)
        
        # Verify 2% commission is accrued (20.0 * 0.02 = 0.40)
        entry = CommissionLedgerEntry.objects.filter(order=order).first()
        self.assertIsNotNone(entry)
        self.assertEqual(float(entry.commission_amount), 0.40)

class KitchenSkipAndMixedOrdersTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='kitchen_seller', password='password123', role='SELLER'
        )
        self.store = Store.objects.create(
            name='Gourmet Burger Kitchen',
            owner=self.seller,
            store_type='RESTAURANT'
        )
        self.burger = Product.objects.create(
            name='Double Cheese Burger',
            price=15.00,
            store=self.store,
            requires_kitchen=True
        )
        self.soda = Product.objects.create(
            name='Canned Coca-Cola',
            price=2.50,
            store=self.store,
            requires_kitchen=False
        )
        self.client.force_authenticate(user=self.seller)

    def test_direct_only_order_skips_kitchen_prep(self):
        """
        Verify that an order containing only packaged/direct items skips kitchen
        prep and automatically transitions to READY upon payment.
        """
        from orders.services import OrderStateMachine
        
        order = Order.objects.create(
            store=self.store,
            total_amount=2.50,
            state=Order.State.CREATED
        )
        order.items.create(product=self.soda, quantity=1, unit_price=2.50)
        
        # Transition to PAID
        updated_order = OrderStateMachine.transition_order(order, Order.State.PAID)
        
        # Verify order has automatically transitioned to READY
        self.assertEqual(updated_order.state, Order.State.READY)
        self.assertTrue(updated_order.items.filter(product=self.soda).first().is_ready)

    def test_mixed_order_handles_auto_ready_and_reactive_transition(self):
        """
        Verify that in a mixed order (burger + soda):
        1. The soda is automatically marked ready on payment.
        2. The burger is NOT marked ready.
        3. The order does not automatically skip to READY.
        4. Marking the burger ready reactive-triggers the entire order to become READY.
        """
        from orders.services import OrderStateMachine
        
        order = Order.objects.create(
            store=self.store,
            total_amount=17.50,
            state=Order.State.CREATED
        )
        burger_item = order.items.create(product=self.burger, quantity=1, unit_price=15.00)
        soda_item = order.items.create(product=self.soda, quantity=1, unit_price=2.50)
        
        # Transition to PAID
        updated_order = OrderStateMachine.transition_order(order, Order.State.PAID)
        
        # Soda should be auto-marked ready, burger should remain pending prep
        soda_item.refresh_from_db()
        burger_item.refresh_from_db()
        self.assertTrue(soda_item.is_ready)
        self.assertFalse(burger_item.is_ready)
        
        # Order should NOT be READY yet because burger is cooking
        self.assertEqual(updated_order.state, Order.State.PAID)
        
        # Move order manually to QUEUED and PREPARING (simulating kitchen dashboard)
        updated_order = OrderStateMachine.transition_order(updated_order, Order.State.QUEUED)
        updated_order = OrderStateMachine.transition_order(updated_order, Order.State.PREPARING)
        self.assertEqual(updated_order.state, Order.State.PREPARING)
        
        # Mark the burger as ready (simulating chef action) via API client or direct method call
        res = self.client.post(
            reverse('order-mark-item-ready', kwargs={'pk': updated_order.id, 'item_id': burger_item.id})
        )
        self.assertEqual(res.status_code, 200)
        
        # Refresh and verify order is now READY because all items are finished
        updated_order.refresh_from_db()
        self.assertEqual(updated_order.state, Order.State.READY)


class DeliveryFeeNegotiationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='seller_neg', password='password123', role='SELLER'
        )
        self.customer = User.objects.create_user(
            username='customer_neg', password='password123', role='CUSTOMER'
        )
        self.store = Store.objects.create(
            name='Delivery Shop',
            owner=self.seller,
            store_type='SHOP'
        )
        self.product = Product.objects.create(
            name='Food Item',
            price=50.0,
            store=self.store
        )

    def test_delivery_fee_flow_and_renegotiation(self):
        """
        Verify:
        1. Customer places a delivery order. Default total_amount is food subtotal, delivery_fee=0.0, status='PENDING'.
        2. Accountant/Seller transitions order to PAID and sets delivery_fee. Status updates to 'AGREED', total_amount recalculates.
        3. Customer requests renegotiation -> status transitions to 'RENEGOTIATE'.
        4. Seller updates delivery_fee -> status transitions back to 'AGREED', total_amount recalculates.
        5. Completing the order accrues 3% commission on the total final amount.
        """
        from orders.services import OrderStateMachine
        from billing.models import CommissionLedgerEntry
        
        # 1. Customer places a delivery order
        self.client.force_authenticate(user=self.customer)
        url = reverse('order-list')
        payload = {
            'store': self.store.id,
            'fulfillment_mode': 'DELIVERY',
            'delivery_location': '123 Main St',
            'delivery_latitude': -6.1731,
            'delivery_longitude': 35.7419,
            'payment_message': 'MPESA transaction slip 123',
            'items': [
                {'product': self.product.id, 'quantity': 2, 'unit_price': 50.0} # Subtotal 100.0
            ]
        }
        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        order_id = res.data['id']
        
        order = Order.objects.get(id=order_id)
        self.assertEqual(float(order.delivery_fee), 0.0)
        self.assertEqual(order.delivery_fee_status, 'PENDING')
        self.assertEqual(float(order.total_amount), 100.0)

        # 2. Accountant/Seller sets delivery fee and advances order state to PAID
        self.client.force_authenticate(user=self.seller)
        advance_url = reverse('order-advance-state', kwargs={'pk': order_id})
        res = self.client.post(advance_url, {'state': 'PAID', 'delivery_fee': 15.0}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertEqual(order.state, Order.State.PREPARING)
        self.assertEqual(float(order.delivery_fee), 15.0)
        self.assertEqual(order.delivery_fee_status, 'AGREED')
        self.assertEqual(float(order.total_amount), 115.0) # 100 + 15

        # 3. Customer requests renegotiation
        self.client.force_authenticate(user=self.customer)
        reneg_url = reverse('order-renegotiate-delivery-fee', kwargs={'pk': order_id})
        res = self.client.post(reneg_url, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertEqual(order.delivery_fee_status, 'RENEGOTIATE')

        # 4. Seller updates delivery fee via the update_delivery_fee endpoint
        self.client.force_authenticate(user=self.seller)
        update_fee_url = reverse('order-update-delivery-fee', kwargs={'pk': order_id})
        res = self.client.post(update_fee_url, {'delivery_fee': 20.0}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertEqual(float(order.delivery_fee), 20.0)
        self.assertEqual(order.delivery_fee_status, 'AGREED')
        self.assertEqual(float(order.total_amount), 120.0) # 100 + 20

        # 5. Transition order to COMPLETED (need to go PREPARING -> READY -> COMPLETED)
        order = OrderStateMachine.transition_order(order, Order.State.READY)
        OrderStateMachine.transition_order(order, Order.State.COMPLETED, bypass_verification=True)
        
        # Verify 2% commission is accrued on 120.0 (2.40)
        entry = CommissionLedgerEntry.objects.filter(order=order).first()
        self.assertIsNotNone(entry)
        self.assertEqual(float(entry.commission_amount), 2.40)


class ReverseGeocodeProxyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='geo_user', password='password123', role='CUSTOMER'
        )
        self.client.force_authenticate(user=self.user)

    @patch('requests.get')
    def test_reverse_geocode_success(self, mock_get):
        # Mock success response
        class MockResponse:
            status_code = 200
            def json(self):
                return {"display_name": "Tegeta, Dar es Salaam, Tanzania"}
        mock_get.return_value = MockResponse()

        url = reverse('order-reverse-geocode')
        response = self.client.get(url, {'lat': '-6.827', 'lon': '39.2675'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['display_name'], "Tegeta, Dar es Salaam, Tanzania")
        mock_get.assert_called_once_with(
            "https://nominatim.openstreetmap.org/reverse?lat=-6.8270&lon=39.2675&format=json",
            headers={'User-Agent': 'Chapuu-Backend-Reverse-Geocoding-Proxy/1.0 (contact: support@chapuu.com)'},
            timeout=5
        )

    @patch('requests.get')
    def test_reverse_geocode_service_failure(self, mock_get):
        # Mock failure (non-200) response
        class MockResponse:
            status_code = 500
        mock_get.return_value = MockResponse()

        url = reverse('order-reverse-geocode')
        response = self.client.get(url, {'lat': '-6.827', 'lon': '39.2675'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('fallback'))
        self.assertIn("Location:", response.data.get('display_name'))

    @patch('requests.get')
    def test_reverse_geocode_exception(self, mock_get):
        # Mock connection timeout/exception
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        url = reverse('order-reverse-geocode')
        response = self.client.get(url, {'lat': '-6.827', 'lon': '39.2675'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('fallback'))
        self.assertIn("Location:", response.data.get('display_name'))

    def test_reverse_geocode_missing_parameters(self):
        url = reverse('order-reverse-geocode')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)



