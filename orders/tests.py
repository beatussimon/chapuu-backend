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
        
        # Verify 3% commission is accrued (20.0 * 0.03 = 0.60)
        entry = CommissionLedgerEntry.objects.filter(order=order).first()
        self.assertIsNotNone(entry)
        self.assertEqual(float(entry.commission_amount), 0.60)
