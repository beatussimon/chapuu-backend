from django.shortcuts import render
import hmac
import hashlib
import time
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from payments.models import Payment
from orders.services import OrderStateMachine
from orders.models import Order
from catalog.services import InventoryEngine
from stores.services import KitchenEngine
import logging

logger = logging.getLogger(__name__)

class ZenopayWebhookView(APIView):
    """
    Handles incoming webhooks from Zenopay seamlessly.
    Employs strict idempotency to prevent duplicate processing.
    """

    def post(self, request, *args, **kwargs):
        # Read raw body first for HMAC signature verification before parsing JSON
        raw_body = request.body
        payload = request.data
        
        # 1. Validation (HMAC or secret matching depending on Zenopay spec)
        signature = request.headers.get("X-Zenopay-Signature", "")
        expected_secret = getattr(settings, 'ZENOPAY_WEBHOOK_SECRET', 'test_secret')
        
        if not self._verify_signature(raw_body, signature, expected_secret):
            return Response({"error": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)
            
        transaction_id = payload.get("transaction_id")
        payment_status = payload.get("status") # e.g., 'COMPLETED', 'FAILED'
        order_id = payload.get("order_id")

        if not transaction_id or not order_id:
            return Response({"error": "Missing critical webhook fields"}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Idempotency Check
        with transaction.atomic():
            try:
                payment = Payment.objects.get(order_id=order_id)
            except Payment.DoesNotExist:
                logger.error(f"Payment record not found for webhook order {order_id}")
                return Response({"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

            # Idempotency check: if already processed, return 200 immediately
            if payment.status in [Payment.Status.SUCCESS, Payment.Status.FAILED]:
                logger.info(f"Webhook already processed for payment {payment.id}")
                return Response({"message": "Already processed"}, status=status.HTTP_200_OK)

            if payment_status == "COMPLETED":
                # Process Success Flow
                payment.status = Payment.Status.SUCCESS
                payment.provider_transaction_id = transaction_id
                payment.save(update_fields=['status', 'provider_transaction_id', 'updated_at'])

                # 3. Trigger Domain Engines
                if payment.order:
                    order = payment.order
                    # Use the state machine to transition the order
                    OrderStateMachine.transition_order(order, Order.State.PAID)
                    
                    # Deduct stock atomically
                    try:
                        InventoryEngine.deduct_stock_for_order(order)
                    except Exception as e:
                        logger.error(f"Inventory deduction failed post-payment: {e}")
                    
                    # Push to Kitchen Queue if required
                    KitchenEngine.enqueue_order(order)
                
                # If reservation deposit, trigger reservation active
                elif payment.reservation:
                    payment.reservation.status = 'CONFIRMED'
                    payment.reservation.save()

            elif payment_status == "FAILED":
                payment.status = Payment.Status.FAILED
                payment.provider_transaction_id = transaction_id
                payment.save(update_fields=['status', 'provider_transaction_id', 'updated_at'])

                if payment.order:
                    try:
                        OrderStateMachine.transition_order(payment.order, Order.State.CANCELLED, notes="Payment failed.")
                    except Exception as e:
                         logger.error(f"Cancellation failed post-payment: {e}")

        return Response({"message": "Webhook processed successfully"}, status=status.HTTP_200_OK)

    def _verify_signature(self, payload_body: bytes, signature: str, secret: str) -> bool:
        if getattr(settings, 'DEBUG', False) and secret == 'test_secret': # Allows unauthenticated local testing
            return True
            
        if not signature:
            return False
            
        expected_mac = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_mac, signature)

