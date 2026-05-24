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

from django.core.cache import cache

class BillboardStatsViewSet(viewsets.ViewSet):
    """
    Publicly accessible endpoint for the Landing Page to display dynamic analytics.
    """
    permission_classes = [permissions.AllowAny]

    def list(self, request):
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')

        # Only cache global stats (no lat/lng) to prevent cache explosion
        # Personalized/Location-based stats remain dynamic for accuracy
        if not lat or not lng:
            cache_key = "billboard_stats_global"
            cached_data = cache.get(cache_key)
            if cached_data:
                return Response(cached_data)

        # 1. Total Metrics
        total_stores = Store.objects.filter(is_active=True).count()
        total_meals = Order.objects.filter(state=Order.State.COMPLETED, store__is_active=True).count()
        
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        
        if lat and lng:
            try:
                lat_f = float(lat)
                lng_f = float(lng)
                
                # Fetch stores and annotate distance
                stores = list(Store.objects.filter(is_active=True).prefetch_related('payment_methods', 'kitchen_settings'))
                from stores.geo_utils import annotate_distances
                stores = annotate_distances(stores, lat_f, lng_f)
                
                from catalog.recommendations import score_stores, score_products
                scored_stores = score_stores(stores, lat_f, lng_f, max_radius_km=5.0, user=request.user)
                top_stores = scored_stores[:4]
                
                # Fetch products and score them - pre-filtered by nearby store IDs to prevent loading the entire database
                nearby_store_ids = [s.id for s in scored_stores if getattr(s, 'distance_km', 999.0) <= 5.0]
                products = list(Product.objects.select_related('store', 'stock').prefetch_related('recipe_ingredients__ingredient__stock').filter(is_active=True, store__is_active=True, store_id__in=nearby_store_ids))
                # Exclude out-of-stock items
                products = [p for p in products if p.check_stock_available(1)[0]]
                # Add distance_km map
                store_dist_map = {s.id: getattr(s, 'distance_km', None) for s in stores}
                for p in products:
                    p.distance_km = store_dist_map.get(p.store_id, None)
                    
                scored_products = score_products(products, lat_f, lng_f, max_radius_km=5.0, user=request.user)
                trending_products = scored_products[:4]
                
                # Map to response format
                top_stores_data = []
                for store in top_stores:
                    completed_orders = Order.objects.filter(store=store, state=Order.State.COMPLETED).count()
                    top_stores_data.append({
                        'id': store.id,
                        'name': store.name,
                        'location': store.location,
                        'completed_orders': completed_orders,
                        'distance_km': getattr(store, 'distance_km', None),
                        'image_url': request.build_absolute_uri(store.image.url) if store.image else None
                    })
                    
                trending_products_data = []
                for prod in trending_products:
                    total_ordered = prod.order_items.filter(order__state=Order.State.COMPLETED).aggregate(total=Sum('quantity'))['total'] or 0
                    trending_products_data.append({
                        'id': prod.id,
                        'name': prod.name,
                        'store_id': prod.store.id,
                        'store_name': prod.store.name,
                        'price': str(prod.price),
                        'times_ordered': total_ordered,
                        'distance_km': getattr(prod, 'distance_km', None),
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
            except (ValueError, TypeError):
                pass
                
        # Default behavior when no lat/lng
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
                'distance_km': None,
                'image_url': request.build_absolute_uri(store.image.url) if store.image else None
            })
        
        # 3. Trending Items (by order item count in completed orders)
        trending_products_raw = Product.objects.select_related('store', 'stock').prefetch_related('recipe_ingredients__ingredient__stock').filter(
            is_active=True,
            store__is_active=True
        ).annotate(
            times_ordered=Sum('order_items__quantity', filter=models.Q(order_items__order__state=Order.State.COMPLETED))
        ).order_by('-times_ordered')

        trending_products = []
        for prod in trending_products_raw:
            if prod.check_stock_available(1)[0]:
                trending_products.append(prod)
                if len(trending_products) >= 4:
                    break

        trending_products_data = []
        for prod in trending_products:
            trending_products_data.append({
                'id': prod.id,
                'name': prod.name,
                'store_id': prod.store.id,
                'store_name': prod.store.name,
                'price': str(prod.price),
                'times_ordered': prod.times_ordered or 0,
                'distance_km': None,
                'image_url': request.build_absolute_uri(prod.image.url) if prod.image else None
            })

        response_data = {
            'metrics': {
                'total_stores': total_stores,
                'total_meals_served': total_meals,
            },
            'top_stores': top_stores_data,
            'trending_items': trending_products_data
        }

        if not lat or not lng:
            cache.set("billboard_stats_global", response_data, 60*60) # Cache for 1 hour

        return Response(response_data)

