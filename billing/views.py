from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum, Count, Avg, Q
from datetime import timedelta
from decimal import Decimal
from stores.models import Store
from users.permissions import IsPlatformAdmin
from rest_framework.pagination import PageNumberPagination
from billing.models import CommissionLedgerEntry, MonthlyInvoice, CommissionPayment, PlatformPaymentMethod
from billing.serializers import (
    CommissionLedgerEntrySerializer, MonthlyInvoiceSerializer, 
    CommissionPaymentSerializer, PlatformPaymentMethodSerializer
)

class IsSellerOrAdmin(permissions.BasePermission):

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and (request.user.role in ['SELLER', 'ADMIN', 'SUPERUSER'] or request.user.is_superuser)

class CommissionLedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CommissionLedgerEntrySerializer
    permission_classes = [IsSellerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return CommissionLedgerEntry.objects.all()
        return CommissionLedgerEntry.objects.filter(store__owner=user)

class MonthlyInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MonthlyInvoiceSerializer
    permission_classes = [IsSellerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return MonthlyInvoice.objects.all()
        return MonthlyInvoice.objects.filter(store__owner=user)

class CommissionPaymentViewSet(viewsets.ModelViewSet):
    serializer_class = CommissionPaymentSerializer
    permission_classes = [IsSellerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['ADMIN', 'SUPERUSER'] or user.is_superuser:
            return CommissionPayment.objects.all()
        return CommissionPayment.objects.filter(invoice__store__owner=user)

    def perform_create(self, serializer):
        invoice = serializer.validated_data['invoice']
        # Enforce that the user is the owner of the store for this invoice
        is_admin_or_su = self.request.user.role in ['ADMIN', 'SUPERUSER'] or self.request.user.is_superuser
        if not is_admin_or_su and invoice.store.owner != self.request.user:
            raise ValidationError("You do not have permission to submit a payment for this invoice.")
        
        # Save payment and set invoice status to PENDING_REVIEW
        payment = serializer.save(submitted_by=self.request.user, status=CommissionPayment.Status.PENDING)
        invoice.status = MonthlyInvoice.Status.PENDING_REVIEW
        invoice.save(update_fields=['status'])

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def review(self, request, pk=None):
        if request.user.role not in ['ADMIN', 'SUPERUSER'] and not request.user.is_superuser:
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
        from users.permissions import IsSuperUser
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [IsSuperUser()]


class PlatformBillingPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class PlatformBillingOverviewViewSet(viewsets.ViewSet):
    permission_classes = [IsPlatformAdmin]
    pagination_class = PlatformBillingPagination

    def list(self, request):
        stores = Store.objects.select_related('owner').order_by('name')
        
        search = request.query_params.get('search', '')
        if search:
            stores = stores.filter(
                Q(name__icontains=search) | Q(owner__username__icontains=search)
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(stores, request, view=self)

        data = []
        target_stores = page if page is not None else stores

        for store in target_stores:
            completed_orders = store.orders.filter(state='COMPLETED')
            total_sales = completed_orders.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            order_count = completed_orders.count()

            commission_entries = store.commission_entries.all()
            total_commission = commission_entries.aggregate(total=Sum('commission_amount'))['total'] or Decimal('0.00')

            unpaid_invoices = store.invoices.filter(status__in=['UNPAID', 'OVERDUE', 'PENDING_REVIEW'])
            amount_owed = unpaid_invoices.filter(status__in=['UNPAID', 'OVERDUE']).aggregate(total=Sum('total_commission'))['total'] or Decimal('0.00')
            pending_payout_amount = unpaid_invoices.filter(status='PENDING_REVIEW').aggregate(total=Sum('total_commission'))['total'] or Decimal('0.00')

            paid_invoices = store.invoices.filter(status='PAID')
            total_paid = paid_invoices.aggregate(total=Sum('total_commission'))['total'] or Decimal('0.00')

            data.append({
                'store_id': store.id,
                'store_name': store.name,
                'owner_username': store.owner.username,
                'is_active': store.is_active,
                'store_type': store.store_type,
                'total_sales': float(total_sales),
                'order_count': order_count,
                'total_commission': float(total_commission),
                'amount_owed': float(amount_owed),
                'pending_payout': float(pending_payout_amount),
                'total_paid': float(total_paid),
                'unpaid_invoice_count': unpaid_invoices.filter(status__in=['UNPAID', 'OVERDUE']).count(),
                'pending_invoice_count': unpaid_invoices.filter(status='PENDING_REVIEW').count(),
            })

        if page is not None:
            return paginator.get_paginated_response(data)
        return Response(data)

    @action(detail=False, methods=['get'])
    def rankings(self, request):
        # 1. Most Sales (Top GPV)
        top_sales = Store.objects.annotate(
            sales_val=Sum('orders__total_amount', filter=Q(orders__state='COMPLETED'))
        ).filter(sales_val__gt=0).order_by('-sales_val')[:5]

        sales_rankings = []
        for s in top_sales:
            sales_rankings.append({
                'store_id': s.id,
                'store_name': s.name,
                'value': float(s.sales_val or 0)
            })

        # 2. Loved by Users (Highest Avg Rating)
        loved_stores = Store.objects.annotate(
            avg_rating=Avg('reviews__rating'),
            rating_count=Count('reviews')
        ).filter(rating_count__gt=0).order_by('-avg_rating', '-rating_count')[:5]

        loved_rankings = []
        for s in loved_stores:
            loved_rankings.append({
                'store_id': s.id,
                'store_name': s.name,
                'rating': float(s.avg_rating or 0),
                'rating_count': s.rating_count
            })

        # 3. Lazy Stores (Low Completed Order Count, created at least 3 days ago)
        three_days_ago = timezone.now() - timedelta(days=3)
        lazy_stores = Store.objects.filter(
            created_at__lte=three_days_ago
        ).annotate(
            order_cnt=Count('orders', filter=Q(orders__state='COMPLETED'))
        ).order_by('order_cnt')[:5]

        lazy_rankings = []
        for s in lazy_stores:
            lazy_rankings.append({
                'store_id': s.id,
                'store_name': s.name,
                'value': s.order_cnt,
                'created_at': s.created_at.date().isoformat()
            })

        # 4. Highest Transaction Count (Velocity)
        top_orders = Store.objects.annotate(
            order_cnt=Count('orders', filter=Q(orders__state='COMPLETED'))
        ).filter(order_cnt__gt=0).order_by('-order_cnt')[:5]

        order_rankings = []
        for s in top_orders:
            order_rankings.append({
                'store_id': s.id,
                'store_name': s.name,
                'value': s.order_cnt
            })

        return Response({
            'most_sales': sales_rankings,
            'loved': loved_rankings,
            'lazy': lazy_rankings,
            'most_orders': order_rankings
        })

