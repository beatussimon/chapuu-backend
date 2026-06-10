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
        offset = int(request.query_params.get('offset', 0))

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
            # Optimize to avoid multi-table LEFT OUTER JOINs and DISTINCT on stores
            matched_category_ids = list(Category.objects.filter(name__icontains=q).values_list('id', flat=True))
            
            direct_store_ids = list(Store.objects.filter(is_active=True).filter(
                Q(name__icontains=q) | Q(location__icontains=q)
            ).values_list('id', flat=True))
            
            category_store_ids = list(Category.objects.filter(
                id__in=matched_category_ids
            ).exclude(store__isnull=True).values_list('store_id', flat=True))
            
            product_store_ids = list(Product.objects.filter(
                is_active=True
            ).filter(
                Q(name__icontains=q) |
                Q(description__icontains=q) |
                Q(category_id__in=matched_category_ids)
            ).values_list('store_id', flat=True))
            
            matched_store_ids = set(direct_store_ids + category_store_ids + product_store_ids)
            matched_store_ids.discard(None)
            
            stores_qs = stores_qs.filter(id__in=matched_store_ids)

            # Optimize to avoid joins on products
            matched_store_ids_by_name = list(Store.objects.filter(is_active=True, name__icontains=q).values_list('id', flat=True))
            
            products_qs = products_qs.filter(
                Q(name__icontains=q) |
                Q(description__icontains=q) |
                Q(category_id__in=matched_category_ids) |
                Q(store_id__in=matched_store_ids_by_name)
            )
            
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
                # Only convert to list here because haversine needs objects for math
                stores_list = annotate_distances(list(stores_qs), lat, lng)
                
                # Filter by radius if a non-zero radius is requested
                if radius > 0:
                    stores_list = filter_by_radius(stores_list, radius)
                
                # Filter products to only those from stores within the radius/proximity list in the database
                # Efficiently filter using the IDs of already-filtered stores
                allowed_store_ids = {s.id for s in stores_list}
                products_qs = products_qs.filter(store_id__in=allowed_store_ids)
            except (ValueError, TypeError):
                stores_list = list(stores_qs)
        else:
            stores_list = list(stores_qs)

        products_list = list(products_qs)

        # Apply scoring algorithms
        scoring_radius = radius if (lat and lng and radius > 0) else 2.0
        scored_stores = score_stores(stores_list, lat, lng, scoring_radius, request.user, q)
        scored_products = score_products(products_list, lat, lng, scoring_radius, request.user, q)

        # Limit results size
        final_stores = scored_stores[offset:offset+limit]
        final_products = scored_products[offset:offset+limit]
        final_categories = list(categories_qs)[offset:offset+limit]

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
            item['store_id'] = final_products[i].store_id

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

        # Next / Prev URL calculation
        from django.utils.http import urlencode
        base_url = request.build_absolute_uri(request.path)
        
        # Build query parameters base dictionary
        params = {}
        if q: params['q'] = q
        if search_type != 'all': params['type'] = search_type
        if lat: params['lat'] = lat
        if lng: params['lng'] = lng
        if radius != '2.0': params['radius'] = radius
        if category_id: params['category'] = category_id
        if store_type: params['store_type'] = store_type
        if is_open: params['is_open'] = is_open
        params['limit'] = limit
        
        next_url = None
        has_next = (
            (len(scored_stores) > offset + limit) or 
            (len(scored_products) > offset + limit) or 
            (categories_qs.count() > offset + limit)
        )
        if has_next:
            next_params = params.copy()
            next_params['offset'] = offset + limit
            next_url = f"{base_url}?{urlencode(next_params)}"
            
        prev_url = None
        if offset > 0:
            prev_params = params.copy()
            prev_params['offset'] = max(0, offset - limit)
            prev_url = f"{base_url}?{urlencode(prev_params)}"

        return Response({
            "query": q,
            "results": results,
            "total_count": total_count,
            "location_active": location_active,
            "next": next_url,
            "previous": prev_url
        })
