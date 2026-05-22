from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.core.exceptions import ValidationError
from billing.models import CommissionLedgerEntry, MonthlyInvoice, CommissionPayment, PlatformPaymentMethod
from billing.serializers import (
    CommissionLedgerEntrySerializer, MonthlyInvoiceSerializer, 
    CommissionPaymentSerializer, PlatformPaymentMethodSerializer
)

class IsSellerOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['SELLER', 'ADMIN']

class CommissionLedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CommissionLedgerEntrySerializer
    permission_classes = [IsSellerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return CommissionLedgerEntry.objects.all()
        return CommissionLedgerEntry.objects.filter(store__owner=user)

class MonthlyInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MonthlyInvoiceSerializer
    permission_classes = [IsSellerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return MonthlyInvoice.objects.all()
        return MonthlyInvoice.objects.filter(store__owner=user)

class CommissionPaymentViewSet(viewsets.ModelViewSet):
    serializer_class = CommissionPaymentSerializer
    permission_classes = [IsSellerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return CommissionPayment.objects.all()
        return CommissionPayment.objects.filter(invoice__store__owner=user)

    def perform_create(self, serializer):
        invoice = serializer.validated_data['invoice']
        # Enforce that the user is the owner of the store for this invoice
        if self.request.user.role != 'ADMIN' and invoice.store.owner != self.request.user:
            raise ValidationError("You do not have permission to submit a payment for this invoice.")
        
        # Save payment and set invoice status to PENDING_REVIEW
        payment = serializer.save(submitted_by=self.request.user, status=CommissionPayment.Status.PENDING)
        invoice.status = MonthlyInvoice.Status.PENDING_REVIEW
        invoice.save(update_fields=['status'])

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def review(self, request, pk=None):
        if request.user.role != 'ADMIN':
            return Response({"error": "Permission denied. Only admins can review payments."}, status=status.HTTP_403_FORBIDDEN)
        
        payment = self.get_object()
        if payment.status != CommissionPayment.Status.PENDING:
            return Response({"error": "This payment has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)
        
        approved = request.data.get('approved', False)
        rejection_reason = request.data.get('rejection_reason', '')

        payment.status = CommissionPayment.Status.APPROVED if approved else CommissionPayment.Status.REJECTED
        payment.rejection_reason = rejection_reason
        payment.reviewed_by = request.user
        payment.reviewed_at = timezone.now()
        payment.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at'])

        # Update invoice status
        invoice = payment.invoice
        if approved:
            invoice.status = MonthlyInvoice.Status.PAID
        else:
            invoice.status = MonthlyInvoice.Status.UNPAID
        invoice.save(update_fields=['status'])

        return Response({"status": f"Payment {payment.status.lower()}", "payment_status": payment.status})

class PlatformPaymentMethodViewSet(viewsets.ModelViewSet):
    serializer_class = PlatformPaymentMethodSerializer
    queryset = PlatformPaymentMethod.objects.filter(is_active=True)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]
