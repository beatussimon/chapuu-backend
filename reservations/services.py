from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from django.core.exceptions import ValidationError
from reservations.models import Reservation, TableSession
from stores.models import Store, Table

class ReservationEngine:
    @classmethod
    def is_table_available(cls, table: Table, requested_time, duration_minutes: int, exclude_reservation_id=None) -> bool:
        """
        Checks if the table is free during the requested timeframe.
        """
        start_time = requested_time
        end_time = requested_time + timedelta(minutes=duration_minutes)

        # SQLite doesn't natively do easy timeframe math in Django ORM,
        # so we fetch potential collisions on the same day and filter in python.
        day_start = requested_time.replace(hour=0, minute=0, second=0)
        day_end = day_start + timedelta(days=1)
        
        candidates = Reservation.objects.filter(
            table=table,
            # We don't consider cancelled/no-shows as blocking
            status__in=[Reservation.Status.CONFIRMED, Reservation.Status.ACTIVE],
            reservation_time__range=(day_start, day_end)
        )
        
        if exclude_reservation_id:
            candidates = candidates.exclude(id=exclude_reservation_id)

        for res in candidates:
            res_end = res.reservation_time + timedelta(minutes=res.duration_minutes)
            if start_time < res_end and end_time > res.reservation_time:
                return False # Overlap found!
                
        return True

    @classmethod
    def create_reservation(cls, store: Store, customer, reservation_time, duration_minutes: int, guest_count: int, table: Table = None):
        """
        Attempts to create a reservation. Auto-assigns table if not provided.
        Uses select_for_update to prevent race conditions during concurrent bookings.
        """
        from django.db import transaction
        
        with transaction.atomic():
            if table:
                # Lock the table record for this transaction
                locked_table = Table.objects.select_for_update().get(id=table.id)
                if not cls.is_table_available(locked_table, reservation_time, duration_minutes):
                    raise ValueError("Table is not available for the requested time.")
                table = locked_table
            else:
                # Find an available table (sorted by capacity ascending to optimize seating) and lock it
                tables = Table.objects.filter(store=store, is_active=True, capacity__gte=guest_count).order_by('capacity').select_for_update()
                found = False
                for t in tables:
                    if cls.is_table_available(t, reservation_time, duration_minutes):
                        table = t
                        found = True
                        break
                if not found:
                    raise ValueError("No tables available for the requested details.")
            
            reservation = Reservation.objects.create(
                store=store,
                customer=customer,
                table=table,
                reservation_time=reservation_time,
                duration_minutes=duration_minutes,
                guest_count=guest_count,
                status=Reservation.Status.PENDING # Awaiting deposit/confirmation
            )
            return reservation

    @classmethod
    def activate_reservation(cls, reservation: Reservation):
        """
        Converts a reservation to an active Table Session upon arrival.
        """
        if TableSession.objects.filter(table=reservation.table, is_active=True).exists():
            raise ValidationError("Table is already occupied by another active session.")

        reservation.status = Reservation.Status.ACTIVE
        reservation.save(update_fields=['status'])
        
        session = TableSession.objects.create(
            store=reservation.store,
            table=reservation.table,
            reservation=reservation
        )
        return session

    @classmethod
    def create_walk_in(cls, store: Store, customer, duration_minutes: int, guest_count: int, table: Table = None):
        """
        Atomically creates a walk-in reservation (directly ACTIVE) and spawns its TableSession.
        """
        from django.db import transaction
        
        with transaction.atomic():
            now = timezone.now()
            if table:
                locked_table = Table.objects.select_for_update().get(id=table.id)
                if not cls.is_table_available(locked_table, now, duration_minutes):
                    raise ValueError("Table is not available.")
                if TableSession.objects.filter(table=locked_table, is_active=True).exists():
                    raise ValueError("Table is already occupied by an active session.")
                table = locked_table
            else:
                # Find an available table (sorted by capacity ascending to optimize seating) and lock it
                tables = Table.objects.filter(store=store, is_active=True, capacity__gte=guest_count).order_by('capacity').select_for_update()
                found = False
                for t in tables:
                    if cls.is_table_available(t, now, duration_minutes) and not TableSession.objects.filter(table=t, is_active=True).exists():
                        table = t
                        found = True
                        break
                if not found:
                    raise ValueError("No tables available for the requested details.")
            
            reservation = Reservation.objects.create(
                store=store,
                customer=customer,
                table=table,
                reservation_time=now,
                duration_minutes=duration_minutes,
                guest_count=guest_count,
                status=Reservation.Status.ACTIVE
            )
            
            TableSession.objects.create(
                store=store,
                table=table,
                reservation=reservation
            )
            
            return reservation
