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
        now = timezone.now()

        # 1. Auto-expire overdue ACTIVE sessions
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

        # 2. Auto-mark PENDING/CONFIRMED as NO_SHOW if they are 30+ mins late
        expiry_threshold = now - datetime.timedelta(minutes=30)
        late_reservations = Reservation.objects.filter(
            status__in=[Reservation.Status.PENDING, Reservation.Status.CONFIRMED],
            reservation_time__lte=expiry_threshold
        )
        for res in late_reservations:
            res.status = Reservation.Status.NO_SHOW
            res.save(update_fields=['status'])

        if user.role == 'SELLER':
            queryset = Reservation.objects.filter(store__owner=user)
        elif user.role == 'ADMIN':
            queryset = Reservation.objects.all()
        elif user.role in ['CHEF', 'ACCOUNTANT', 'DELIVERY'] and user.employed_store:
            queryset = Reservation.objects.filter(store=user.employed_store)
        else:
            queryset = Reservation.objects.filter(customer=user)

        # Allow filtering by store via query params
        store_id = self.request.query_params.get('store')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        return queryset.order_by('reservation_time')

    def create(self, request, *args, **kwargs):
        data = request.data
        try:
            store_id = data.get('store')
            if not store_id:
                return Response({"error": "Store ID is required."}, status=status.HTTP_400_BAD_REQUEST)
                
            store = Store.objects.get(id=store_id)
            reservation_time_str = data.get('reservation_time')
            if not reservation_time_str:
                return Response({"error": "reservation_time is required."}, status=status.HTTP_400_BAD_REQUEST)
                
            try:
                reservation_time = datetime.datetime.fromisoformat(reservation_time_str.replace('Z', '+00:00'))
            except ValueError:
                return Response({"error": "Invalid date/time format."}, status=status.HTTP_400_BAD_REQUEST)
            
            table_id = data.get('table')
            table = None
            if table_id:
                try:
                    table = Table.objects.get(id=table_id, store=store)
                except Table.DoesNotExist:
                    return Response({"error": "Selected table not found in this restaurant."}, status=status.HTTP_404_NOT_FOUND)
            
            try:
                duration = int(data.get('duration_minutes', 60))
                guests = int(data.get('guest_count', 1))
            except (ValueError, TypeError):
                return Response({"error": "Invalid guest count or duration."}, status=status.HTTP_400_BAD_REQUEST)

            reservation = ReservationEngine.create_reservation(
                store=store,
                customer=request.user,
                reservation_time=reservation_time,
                duration_minutes=duration,
                guest_count=guests,
                table=table
            )
            
            serializer = self.get_serializer(reservation)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Store.DoesNotExist:
            return Response({"error": "Restaurant not found."}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            # This catches the 'No tables available' or 'Table is not available' from the engine
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
             # Fallback for unexpected errors, still providing the message
             return Response({"error": f"Internal booking error: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

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

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        reservation = self.get_object()
        
        # Policy: Only owner or customer can cancel
        if request.user != reservation.customer and request.user.role not in ['SELLER', 'ADMIN']:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        # Policy: Check if modification is allowed (re-use the same logic as serializer)
        now = timezone.now()
        threshold = reservation.reservation_time - datetime.timedelta(hours=2)
        
        # Sellers/Admins can always cancel, but customers are bound by the 2hr rule
        if request.user == reservation.customer and now > threshold:
            return Response({"error": "Reservations cannot be cancelled within 2 hours of arrival."}, status=status.HTTP_400_BAD_REQUEST)

        # Transition Reservation
        reservation.status = Reservation.Status.CANCELLED
        reservation.save(update_fields=['status'])

        # Handle linked food order
        linked_order = getattr(reservation, 'linked_order', None)
        if linked_order:
            from orders.services import OrderStateMachine
            from orders.models import Order
            try:
                # If paid, move to REFUNDED, else CANCELLED
                target_state = Order.State.REFUNDED if linked_order.state in [Order.State.PAID, Order.State.QUEUED] else Order.State.CANCELLED
                OrderStateMachine.transition_order(linked_order, target_state, notes=f"Reservation #{reservation.id} cancelled by {request.user.username}")
            except Exception as e:
                print(f"Error auto-cancelling linked order: {e}")

        return Response({"status": "Reservation cancelled"})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def reschedule(self, request, pk=None):
        reservation = self.get_object()
        new_time_str = request.data.get('reservation_time')
        
        if not new_time_str:
            return Response({"error": "new reservation_time is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Policy: Only owner or customer can reschedule
        if request.user != reservation.customer and request.user.role not in ['SELLER', 'ADMIN']:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        # Policy: 2-hour rule for customers
        now = timezone.now()
        if request.user == reservation.customer and now > (reservation.reservation_time - datetime.timedelta(hours=2)):
            return Response({"error": "Reservations cannot be rescheduled within 2 hours of arrival."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_time = datetime.datetime.fromisoformat(new_time_str.replace('Z', '+00:00'))
        except ValueError:
            return Response({"error": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

        # Check availability for the new time (excluding current reservation from overlap check)
        if not ReservationEngine.is_table_available(reservation.table, new_time, reservation.duration_minutes, exclude_reservation_id=reservation.id):
            return Response({"error": "The table is not available at the new requested time."}, status=status.HTTP_400_BAD_REQUEST)

        # Update Reservation
        reservation.reservation_time = new_time
        reservation.save(update_fields=['reservation_time'])

        # Update linked order scheduled time
        linked_order = getattr(reservation, 'linked_order', None)
        if linked_order:
            linked_order.scheduled_time = new_time
            linked_order.save(update_fields=['scheduled_time'])

        return Response({"status": "Reservation rescheduled", "new_time": reservation.reservation_time})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def no_show(self, request, pk=None):
        reservation = self.get_object()
        if request.user.role not in ['SELLER', 'ADMIN', 'CHEF']:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        reservation.status = Reservation.Status.NO_SHOW
        reservation.save(update_fields=['status'])
        return Response({"status": "Marked as NO_SHOW"})


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
