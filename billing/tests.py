from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from users.models import User
from stores.models import Store, KitchenSettings
from catalog.models import Product
from orders.models import Order, OrderItem
from billing.models import CommissionLedgerEntry, MonthlyInvoice
from payments.models import Payment, Refund
from orders.services import OrderStateMachine

class BillingAndVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Admin / Seller setup
        self.seller = User.objects.create_user(
            username='seller', password='password123', role='SELLER'
        )
        self.store = Store.objects.create(
            name='Test Rest',
            owner=self.seller,
            store_type='RESTAURANT'
        )
        # Create KitchenSettings
        self.kitchen_settings = KitchenSettings.objects.create(
            store=self.store,
            max_concurrent_prep_slots=5,
            default_prep_time_minutes=20
        )
        # Customer setup
        self.customer = User.objects.create_user(
            username='customer', password='password123', role='CUSTOMER'
        )
        self.client.force_authenticate(user=self.customer)
        
        self.product = Product.objects.create(
            name='Expensive Burger',
            price=Decimal('15.50'),
            store=self.store,
            estimated_prep_time_minutes=15
        )

    def test_price_tampering_prevention(self):
        """
        Verify that OrderSerializer ignores user-submitted item prices and snapshots
        the database catalog price instead.
        """
        url = reverse('order-list')
        payload = {
            'store': self.store.id,
            'fulfillment_mode': 'DELIVERY',
            'payment_message': 'MPESA-TX-999',
            'items': [
                {
                    'product': self.product.id,
                    'quantity': 2,
                    'unit_price': Decimal('5.00')  # Tampered price
                }
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify order total and items are priced at 15.50, not 5.00
        order = Order.objects.get(id=response.data['id'])
        self.assertEqual(order.total_amount, Decimal('31.00')) # 15.50 * 2
        item = order.items.first()
        self.assertEqual(item.unit_price, Decimal('15.50'))

    def test_handoff_verification_flow(self):
        """
        Verify 6-digit confirmation codes for delivery orders:
        - Generated on OUT_FOR_DELIVERY
        - Direct completion blocked without code verification
        - Attempt tracking and lockout
        - Successful completion with correct code
        """
        # Create order
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            fulfillment_mode='DELIVERY',
            total_amount=Decimal('100.00'),
            state=Order.State.PAID
        )
        
        # Advance through states: PAID -> QUEUED -> PREPARING -> READY -> OUT_FOR_DELIVERY
        OrderStateMachine.transition_order(order, Order.State.QUEUED)
        OrderStateMachine.transition_order(order, Order.State.PREPARING)
        OrderStateMachine.transition_order(order, Order.State.READY)
        
        # Assert delivery code is not generated yet
        order.refresh_from_db()
        self.assertFalse(order.delivery_code)
        
        # Transition to OUT_FOR_DELIVERY
        OrderStateMachine.transition_order(order, Order.State.OUT_FOR_DELIVERY)
        order.refresh_from_db()
        
        # Assert delivery code is generated
        self.assertTrue(order.delivery_code)
        self.assertEqual(len(order.delivery_code), 6)
        self.assertEqual(order.delivery_code_attempts, 0)
        
        # Try to advance to COMPLETED directly (should fail)
        advance_url = reverse('order-advance-state', kwargs={'pk': order.id})
        self.client.force_authenticate(user=self.seller)
        response = self.client.post(advance_url, {'state': 'COMPLETED'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification code required", response.data['error'])
        
        # Try confirm_delivery with invalid code
        confirm_url = reverse('order-confirm-delivery', kwargs={'pk': order.id})
        response = self.client.post(confirm_url, {'code': '000000'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid code", response.data['error'])
        order.refresh_from_db()
        self.assertEqual(order.delivery_code_attempts, 1)
        
        # Verify lockout after 5 attempts
        order.delivery_code_attempts = 4
        order.save()
        response = self.client.post(confirm_url, {'code': '000000'}, format='json')
        order.refresh_from_db()
        self.assertEqual(order.delivery_code_attempts, 5)
        
        response = self.client.post(confirm_url, {'code': order.delivery_code}, format='json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Reset attempts and confirm with correct code
        order.delivery_code_attempts = 0
        order.save()
        
        response = self.client.post(confirm_url, {'code': order.delivery_code}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.state, Order.State.COMPLETED)
        
        # Verify 3% platform commission was created
        ledger = CommissionLedgerEntry.objects.filter(order=order).first()
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.commission_amount, Decimal('3.00')) # 100 * 0.03

    def test_refund_completed_orders_blocked(self):
        """
        Verify that transitioning a COMPLETED order to REFUNDED is strictly forbidden.
        """
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            fulfillment_mode='DINE_IN',
            total_amount=Decimal('50.00'),
            state=Order.State.COMPLETED
        )
        with self.assertRaises(Exception):
            OrderStateMachine.transition_order(order, Order.State.REFUNDED)

    def test_cancellation_fee_scheduled_order(self):
        """
        Verify that a customer cancelling a PAID scheduled order triggers:
        - 6% total fee split
        - 3% to platform commission
        - 94% refund recorded
        """
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            fulfillment_mode='DELIVERY',
            total_amount=Decimal('200.00'),
            state=Order.State.PAID,
            scheduled_time=timezone.now() + timedelta(hours=5)
        )
        Payment.objects.create(
            order=order,
            amount=Decimal('200.00'),
            status=Payment.Status.VERIFIED
        )
        
        # Cancel order as customer
        cancel_url = reverse('order-cancel', kwargs={'pk': order.id})
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(cancel_url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertEqual(order.state, Order.State.CANCELLED)
        
        # Verify platform 3% fee recorded
        ledger = CommissionLedgerEntry.objects.filter(order=order, entry_type=CommissionLedgerEntry.EntryType.CANCELLATION_FEE).first()
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.commission_amount, Decimal('6.00')) # 3% of 200
        
        # Verify 94% refund recorded
        refund = Refund.objects.filter(payment__order=order).first()
        self.assertIsNotNone(refund)
        self.assertEqual(refund.amount, Decimal('188.00')) # 94% of 200
