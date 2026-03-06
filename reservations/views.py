from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.core.exceptions import ValidationError
from reservations.models import Reservation, TableSession
from reservations.serializers import ReservationSerializer, TableSessionSerializer
from reservations.services import ReservationEngine
from stores.models import Table, Store
import datetime

class ReservationViewSet(viewsets.ModelViewSet):
    serializer_class = ReservationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        # Auto-expire overdue ACTIVE reservations
        now = timezone.now()
        overdue_sessions = TableSession.objects.filter(
            is_active=True,
        ).select_related('reservation')
        for session in overdue_sessions:
            if session.reservation and session.reservation.duration_minutes:
                expiry = session.started_at + datetime.timedelta(minutes=session.reservation.duration_minutes)
                if now > expiry:
                    session.is_active = False
                    session.ended_at = now
                    session.save(update_fields=['is_active', 'ended_at'])
                    session.reservation.status = Reservation.Status.COMPLETED
                    session.reservation.save(update_fields=['status'])

        if user.role == 'SELLER':
            return Reservation.objects.filter(store__owner=user).order_by('reservation_time')
        elif user.role == 'ADMIN':
            return Reservation.objects.all().order_by('reservation_time')
        return Reservation.objects.filter(customer=user).order_by('reservation_time')

    def create(self, request, *args, **kwargs):
        data = request.data
        try:
            store = Store.objects.get(id=data.get('store'))
            reservation_time_str = data.get('reservation_time')
            if not reservation_time_str:
                return Response({"error": "reservation_time is required."}, status=status.HTTP_400_BAD_REQUEST)
                
            reservation_time = datetime.datetime.fromisoformat(reservation_time_str.replace('Z', '+00:00'))
            
            table_id = data.get('table')
            table = Table.objects.get(id=table_id) if table_id else None
            
            reservation = ReservationEngine.create_reservation(
                store=store,
                customer=request.user,
                reservation_time=reservation_time,
                duration_minutes=int(data.get('duration_minutes', 60)),
                guest_count=int(data.get('guest_count', 1)),
                table=table
            )
            
            serializer = self.get_serializer(reservation)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Store.DoesNotExist:
            return Response({"error": "Store not found."}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
             return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def confirm(self, request, pk=None):
        """Seller explicitly confirms the reservation (bypassing payment for now)."""
        reservation = self.get_object()
        if request.user.role != 'SELLER' and request.user.role != 'ADMIN':
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        reservation.status = Reservation.Status.CONFIRMED
        reservation.save()
        return Response({"status": "Reservation confirmed", "id": reservation.id})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def check_in(self, request, pk=None):
        reservation = self.get_object()
        if request.user.role != 'SELLER' and request.user.role != 'ADMIN':
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        if reservation.status != Reservation.Status.CONFIRMED:
            return Response({"error": f"Cannot check-in a {reservation.status} reservation."}, status=status.HTTP_400_BAD_REQUEST)
            
        session = ReservationEngine.activate_reservation(reservation)
        return Response({"status": "Checked in", "session_id": session.id})


class TableSessionViewSet(viewsets.ModelViewSet):
    serializer_class = TableSessionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'SELLER':
            return TableSession.objects.filter(store__owner=user, is_active=True)
        elif user.role == 'ADMIN':
            return TableSession.objects.all()
        # Customers don't directly query sessions usually, but can see their own active session
        return TableSession.objects.filter(reservation__customer=user, is_active=True)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def close(self, request, pk=None):
        session = self.get_object()
        if request.user.role != 'SELLER' and request.user.role != 'ADMIN':
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        session.is_active = False
        session.ended_at = timezone.now()
        session.save()
        
        if session.reservation:
            session.reservation.status = Reservation.Status.COMPLETED
            session.reservation.save()
            
        return Response({"status": "Session closed"})
