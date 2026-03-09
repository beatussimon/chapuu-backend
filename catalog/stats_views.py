from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import models
from django.db.models import Count, Sum
from stores.models import Store
from catalog.models import Product
from orders.models import Order
from django.contrib.auth import get_user_model

User = get_user_model()

class BillboardStatsViewSet(viewsets.ViewSet):
    """
    Publicly accessible endpoint for the Landing Page to display dynamic analytics.
    """
    permission_classes = [permissions.AllowAny]

    def list(self, request):
        # 1. Total Metrics
        total_stores = Store.objects.filter(is_active=True).count()
        total_meals = Order.objects.filter(state=Order.State.COMPLETED).count()
        
        # 2. Top Restaurants (by number of completed orders)
        top_stores = Store.objects.filter(is_active=True).annotate(
            completed_orders=Count('orders', filter=models.Q(orders__state=Order.State.COMPLETED))
        ).order_by('-completed_orders')[:4]
        
        top_stores_data = []
        for store in top_stores:
            top_stores_data.append({
                'id': store.id,
                'name': store.name,
                'location': store.location,
                'completed_orders': store.completed_orders,
                'image_url': request.build_absolute_uri(store.image.url) if store.image else None
            })

        # 3. Trending Items (by order item count in completed orders)
        # Assuming simple top products logic based entirely on products linked to finished orders
        trending_products = Product.objects.select_related('store').filter(is_active=True).annotate(
            times_ordered=Sum('order_items__quantity', filter=models.Q(order_items__order__state=Order.State.COMPLETED))
        ).order_by('-times_ordered')[:4]

        trending_products_data = []
        for prod in trending_products:
            trending_products_data.append({
                'id': prod.id,
                'name': prod.name,
                'store_name': prod.store.name,
                'price': str(prod.price),
                'times_ordered': prod.times_ordered or 0,
                'image_url': request.build_absolute_uri(prod.image.url) if prod.image else None
            })

        return Response({
            'metrics': {
                'total_stores': total_stores,
                'total_meals_served': total_meals,
            },
            'top_stores': top_stores_data,
            'trending_items': trending_products_data
        })
