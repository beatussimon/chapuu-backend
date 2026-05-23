from django.urls import path, include
from rest_framework.routers import DefaultRouter
from billing.views import (
    CommissionLedgerEntryViewSet, MonthlyInvoiceViewSet, 
    CommissionPaymentViewSet, PlatformPaymentMethodViewSet,
    PlatformBillingOverviewViewSet
)

router = DefaultRouter()
router.register('ledger', CommissionLedgerEntryViewSet, basename='commissionledgerentry')
router.register('invoices', MonthlyInvoiceViewSet, basename='monthlyinvoice')
router.register('payments', CommissionPaymentViewSet, basename='commissionpayment')
router.register('payment-methods', PlatformPaymentMethodViewSet, basename='platformpaymentmethod')
router.register('platform-billing', PlatformBillingOverviewViewSet, basename='platformbillingoverview')

urlpatterns = [
    path('', include(router.urls)),
]

