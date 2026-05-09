from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from payments.models import Payment
import logging

logger = logging.getLogger(__name__)

# Zenopay has been removed. All payments are offline (M-Pesa, bank transfer, cash).
# Payment verification is handled via OrderViewSet.advance_state(PAID).
# This file is kept for future payment integrations.
