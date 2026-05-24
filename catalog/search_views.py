from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from django.db.models import Q
from stores.models import Store
from stores.serializers import StoreSerializer
from catalog.models import Product, Category
from catalog.serializers import ProductSerializer, CategorySerializer
from catalog.recommendations import score_stores, score_products

class UniversalSearchView(APIView):
    """
    Powerful universal search endpoint for Chapuu.
    Searches across active Stores, Products, and Categories.
    Sorts and filters by coordinates (proximity) when provided.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        q = request.query_params.get('q', '').strip()
        search_type = request.query_params.get('type', 'all')
        
        # Location parameters
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        radius = request.query_params.get('radius', '2.0')
        
        # Additional filters
        category_id = request.query_params.get('category')
        store_type = request.query_params.get('store_type')
        is_open = request.query_params.get('is_open')
        limit = int(request.query_params.get('limit', 20))

        # 1. Base Querysets
        # Only search active stores
        stores_qs = Store.objects.filter(is_active=True).prefetch_related('payment_methods', 'kitchen_settings')
        # Only search active products from active stores
        products_qs = Product.objects.filter(is_active=True, store__is_active=True).select_related('store', 'category').exclude(
            Q(requires_inventory=True, requires_kitchen=False) &
            (Q(stock__isnull=True) | Q(stock__quantity__lte=0))
        )
        categories_qs = Category.objects.all()

        # 2. Text Search Filtering
        if q:
            stores_qs = stores_qs.filter(Q(name__icontains=q) | Q(location__icontains=q))
            products_qs = products_qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
            categories_qs = categories_qs.filter(name__icontains=q)

        # 3. Apply operational filters
        if store_type:
            stores_qs = stores_qs.filter(store_type=store_type)
            products_qs = products_qs.filter(store__store_type=store_type)
            
        if is_open in ['true', 'True', '1']:
            stores_qs = stores_qs.filter(is_open=True)
            products_qs = products_qs.filter(store__is_open=True)
        elif is_open in ['false', 'False', '0']:
            stores_qs = stores_qs.filter(is_open=False)
            products_qs = products_qs.filter(store__is_open=False)
            
        if category_id:
            products_qs = products_qs.filter(category_id=category_id)

        # 4. Proximity Math & Scoring
        stores_list = list(stores_qs)
        products_list = list(products_qs)
        
        # Distance-annotate and filter stores/products if coordinates are present
        location_active = False
        if lat and lng:
            try:
                lat = float(lat)
                lng = float(lng)
                radius = float(radius)
                location_active = True
                
                # Proximity sorting/filtering via Haversine
                from stores.geo_utils import annotate_distances, filter_by_radius
                stores_list = annotate_distances(stores_list, lat, lng)
                
                # Filter by radius if a non-zero radius is requested
                if radius > 0:
                    stores_list = filter_by_radius(stores_list, radius)
                
                # Filter products to only those from stores within the radius/proximity list
                allowed_store_ids = {s.id for s in stores_list}
                products_list = [p for p in products_list if p.store_id in allowed_store_ids]
            except (ValueError, TypeError):
                pass

        # Apply scoring algorithms
        scoring_radius = radius if (lat and lng and radius > 0) else 2.0
        scored_stores = score_stores(stores_list, lat, lng, scoring_radius, request.user, q)
        scored_products = score_products(products_list, lat, lng, scoring_radius, request.user, q)

        # Limit results size
        final_stores = scored_stores[:limit]
        final_products = scored_products[:limit]
        final_categories = list(categories_qs)[:limit]

        # 5. Serialize Response
        # Stores serialization
        serialized_stores = StoreSerializer(final_stores, many=True, context={'request': request}).data
        for i, item in enumerate(serialized_stores):
            item['relevance_score'] = getattr(final_stores[i], 'relevance_score', None)

        # Products serialization + append store details
        serialized_products = ProductSerializer(final_products, many=True, context={'request': request}).data
        for i, item in enumerate(serialized_products):
            item['distance_km'] = getattr(final_products[i], 'distance_km', None)
            item['relevance_score'] = getattr(final_products[i], 'relevance_score', None)
            item['store_name'] = final_products[i].store.name
            item['store_is_open'] = final_products[i].store.is_open

        # Categories serialization
        serialized_categories = CategorySerializer(final_categories, many=True, context={'request': request}).data

        total_count = len(serialized_products) + len(serialized_stores) + len(serialized_categories)

        results = {}
        if search_type == 'all':
            results['products'] = serialized_products
            results['stores'] = serialized_stores
            results['categories'] = serialized_categories
        elif search_type == 'products':
            results['products'] = serialized_products
        elif search_type == 'stores':
            results['stores'] = serialized_stores
        elif search_type == 'categories':
            results['categories'] = serialized_categories

        return Response({
            "query": q,
            "results": results,
            "total_count": total_count,
            "location_active": location_active
        })
