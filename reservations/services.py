from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
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

        overlapping = Reservation.objects.filter(
            table=table,
            status__in=[Reservation.Status.CONFIRMED, Reservation.Status.ACTIVE]
        ).filter(
            Q(reservation_time__lt=end_time) & 
            Q(reservation_time__gte=start_time - timedelta(minutes=60)) # Approximation: assuming mostly 60min blocks. Proper query would need exact duration.
        )
        
        # Proper overlap check using dynamic duration:
        # EndTime = ReservationTime + Duration
        # Overlap Logic: (RequestedStart < ResEnd) AND (RequestedEnd > ResStart)

        # However, SQLite doesn't natively do easy timeframe math in Django ORM,
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
        """
        if table:
            if not cls.is_table_available(table, reservation_time, duration_minutes):
                raise ValueError("Table is not available for the requested time.")
        else:
            # Find an available table
            tables = Table.objects.filter(store=store, is_active=True, capacity__gte=guest_count)
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
        reservation.status = Reservation.Status.ACTIVE
        reservation.save(update_fields=['status'])
        
        session = TableSession.objects.create(
            store=reservation.store,
            table=reservation.table,
            reservation=reservation
        )
        return session
