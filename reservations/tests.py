from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User
from stores.models import Store, Table
from reservations.models import Reservation, TableSession
from reservations.services import ReservationEngine
from django.core.exceptions import ValidationError
import datetime

class ReservationFlowTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='seller', password='password123', role='SELLER'
        )
        self.customer = User.objects.create_user(
            username='customer', password='password123', role='CUSTOMER'
        )
        self.store = Store.objects.create(
            name='Test Restaurant',
            owner=self.seller,
            store_type='RESTAURANT'
        )
        # Create Tables
        self.table_2 = Table.objects.create(
            store=self.store,
            number='2',
            capacity=2,
            is_active=True
        )
        self.table_4 = Table.objects.create(
            store=self.store,
            number='4',
            capacity=4,
            is_active=True
        )
        self.table_10 = Table.objects.create(
            store=self.store,
            number='10',
            capacity=10,
            is_active=True
        )

    def test_table_auto_assignment_optimization(self):
        """Verify table selection optimizes capacity and picks the smallest suitable table."""
        res_time = timezone.now() + datetime.timedelta(days=1)
        
        # A party of 2 should get table_2 (capacity 2)
        res1 = ReservationEngine.create_reservation(
            store=self.store,
            customer=self.customer,
            reservation_time=res_time,
            duration_minutes=60,
            guest_count=2
        )
        self.assertEqual(res1.table, self.table_2)

        # A party of 3 should get table_4 (capacity 4)
        res2 = ReservationEngine.create_reservation(
            store=self.store,
            customer=self.customer,
            reservation_time=res_time,
            duration_minutes=60,
            guest_count=3
        )
        self.assertEqual(res2.table, self.table_4)

    def test_double_session_prevention(self):
        """Verify activating a reservation on an already occupied table fails."""
        res_time = timezone.now()
        res1 = Reservation.objects.create(
            store=self.store,
            customer=self.customer,
            table=self.table_2,
            reservation_time=res_time,
            duration_minutes=60,
            guest_count=2,
            status=Reservation.Status.CONFIRMED
        )
        res2 = Reservation.objects.create(
            store=self.store,
            customer=self.customer,
            table=self.table_2,
            reservation_time=res_time + datetime.timedelta(hours=1),
            duration_minutes=60,
            guest_count=2,
            status=Reservation.Status.CONFIRMED
        )

        # Activate the first reservation
        session1 = ReservationEngine.activate_reservation(res1)
        self.assertTrue(session1.is_active)
        self.assertEqual(res1.status, Reservation.Status.ACTIVE)

        # Attempting to activate the second reservation on the same table should fail
        with self.assertRaises(ValidationError):
            ReservationEngine.activate_reservation(res2)

    def test_confirm_status_guard(self):
        """Verify confirmation action only allows transition from PENDING status."""
        self.client.force_authenticate(user=self.seller)
        res = Reservation.objects.create(
            store=self.store,
            customer=self.customer,
            table=self.table_2,
            reservation_time=timezone.now(),
            duration_minutes=60,
            guest_count=2,
            status=Reservation.Status.ACTIVE
        )

        url = reverse('reservation-confirm', kwargs={'pk': res.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot confirm", response.data['error'])

    def test_no_show_status_guard(self):
        """Verify no_show action only allows transition from PENDING or CONFIRMED."""
        self.client.force_authenticate(user=self.seller)
        res = Reservation.objects.create(
            store=self.store,
            customer=self.customer,
            table=self.table_2,
            reservation_time=timezone.now(),
            duration_minutes=60,
            guest_count=2,
            status=Reservation.Status.ACTIVE
        )

        url = reverse('reservation-no-show', kwargs={'pk': res.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot mark", response.data['error'])

    def test_walk_in_endpoint(self):
        """Verify walk-in creates directly ACTIVE reservation and TableSession."""
        self.client.force_authenticate(user=self.seller)
        url = reverse('reservation-walk-in')
        payload = {
            'store': self.store.id,
            'guest_count': 2,
            'duration_minutes': 90
        }
        
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], Reservation.Status.ACTIVE)
        
        # Verify TableSession was created and is active
        res_id = response.data['id']
        session_exists = TableSession.objects.filter(reservation_id=res_id, is_active=True).exists()
        self.assertTrue(session_exists)
