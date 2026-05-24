import math
from django.utils import timezone
from django.db.models import Avg, Count
from stores.geo_utils import haversine_km
from orders.models import Order
from reviews.models import StoreReview

def proximity_score(distance_km, max_radius_km=2.0):
    """
    Hyper-local Zone: Distance under 300 meters gets perfect 1.0 relevance.
    Beyond 300 meters, decays smoothly using an exponential decay curve.
    """
    if distance_km is None:
        return 0.0
    d = float(distance_km)
    if d <= 0.3:
        return 1.0
    
    # Smooth exponential decay beyond walking distance
    decay_factor = max(float(max_radius_km) * 0.5, 0.5)
    return math.exp(-(d - 0.3) / decay_factor)

def personal_store_score(store_id, user_orders_by_store, now):
    """
    Boost stores based on completed order counts and order recency from pre-fetched in-memory dict.
    """
    orders = user_orders_by_store.get(store_id, [])
    if not orders:
        return 0.0
    
    score = 0.0
    for order in orders:
        days_elapsed = (now - order['created_at']).days
        score += math.exp(-days_elapsed / 30.0)  # Decays exponentially every 30 days
        
    return min(score / 3.0, 1.0)  # Capped at 1.0 (equivalent to ~3 recent monthly orders)

def score_stores(stores_list, lat=None, lng=None, max_radius_km=2.0, user=None, q=None):
    """
    Highly intelligent geolocation and operational metrics scorer for stores.
    Returns the stores list annotated with 'relevance_score' and sorted by relevance.
    """
    if not stores_list:
        return []

    store_ids = [s.id for s in stores_list]
    
    # Pre-fetch totals to prevent N+1 database queries
    order_counts = dict(
        Order.objects.filter(store_id__in=store_ids, state='COMPLETED')
        .values('store_id')
        .annotate(count=Count('id'))
        .values_list('store_id', 'count')
    )
    
    avg_ratings = dict(
        StoreReview.objects.filter(store_id__in=store_ids)
        .values('store_id')
        .annotate(avg=Avg('rating'))
        .values_list('store_id', 'avg')
    )

    max_orders = max(order_counts.values()) if order_counts else 1
    now = timezone.now()

    # Pre-fetch user's completed orders once to prevent N+1 queries in personal_store_score loop
    user_orders_by_store = {}
    if user and user.is_authenticated:
        try:
            # Query all completed orders for this user, ordered by recency
            user_orders = (
                Order.objects.filter(customer=user, store_id__in=store_ids, state='COMPLETED')
                .order_by('-created_at')
                .values('store_id', 'created_at')
            )
            for order in user_orders:
                s_id = order['store_id']
                if s_id not in user_orders_by_store:
                    user_orders_by_store[s_id] = []
                if len(user_orders_by_store[s_id]) < 10:
                    user_orders_by_store[s_id].append(order)
        except Exception:
            pass

    scored_stores = []
    for store in stores_list:
        # 1. Proximity score (40% weight)
        dist = getattr(store, 'distance_km', None)
        if dist is None and lat is not None and lng is not None and store.latitude is not None and store.longitude is not None:
            dist = haversine_km(lat, lng, store.latitude, store.longitude)
            store.distance_km = round(dist, 2) if dist is not None else None
        
        prox_val = proximity_score(dist, max_radius_km) if dist is not None else 0.0

        # 2. Popularity score (Logarithmic scaling, 20% weight)
        order_count = order_counts.get(store.id, 0)
        pop_val = math.log1p(order_count) / max(math.log1p(max_orders), 1.0)

        # 3. Rating score (15% weight)
        avg_rating = avg_ratings.get(store.id, 4.0)  # Default to 4.0 stars if no reviews
        rating_val = float(avg_rating) / 5.0

        # 4. Freshness score (10% weight)
        days_since_creation = (now - store.created_at).days
        fresh_val = math.exp(-days_since_creation / 30.0)  # Decays smoothly over 30 days

        # 5. Personal history score (10% weight)
        pers_val = personal_store_score(store.id, user_orders_by_store, now)

        # 6. Text Query Specificity Match Score (5% weight)
        text_val = 1.0
        if q:
            q_lower = q.lower().strip()
            name_lower = store.name.lower()
            loc_lower = store.location.lower()
            if name_lower == q_lower:
                text_val = 1.0  # Perfect exact match
            elif q_lower in name_lower:
                text_val = 0.8  # Store name substring match
            elif q_lower in loc_lower:
                text_val = 0.3  # Location substring match
            else:
                text_val = 0.0

        # Weighted combination based on coordinate availability
        if dist is None:
            score = (
                0.40 * pop_val +
                0.30 * rating_val +
                0.15 * fresh_val +
                0.10 * pers_val +
                0.05 * text_val
            )
        else:
            score = (
                0.40 * prox_val +
                0.20 * pop_val +
                0.15 * rating_val +
                0.10 * fresh_val +
                0.10 * pers_val +
                0.05 * text_val
            )

        # Operational Availability Multiplier
        if getattr(store, 'is_open', True):
            score *= 1.2
        else:
            score *= 0.3

        store.relevance_score = round(score, 3)
        scored_stores.append(store)

    # Sort descending by relevance score
    scored_stores.sort(key=lambda s: s.relevance_score, reverse=True)
    return scored_stores

def score_products(products_list, lat=None, lng=None, max_radius_km=2.0, user=None, q=None):
    """
    Refined relevance scoring for catalog products.
    Blends parent store's score (50%), product logarithmic popularity (20%), and product text specificity (30%).
    """
    if not products_list:
        return []

    stores_map = {}
    for p in products_list:
        if p.store not in stores_map:
            stores_map[p.store] = []
        stores_map[p.store].append(p)

    scored_stores = score_stores(list(stores_map.keys()), lat, lng, max_radius_km, user, q)
    scored_stores_map = {s.id: s for s in scored_stores}

    product_ids = [p.id for p in products_list]
    from orders.models import OrderItem
    item_counts = dict(
        OrderItem.objects.filter(product_id__in=product_ids, order__state='COMPLETED')
        .values('product_id')
        .annotate(count=Count('id'))
        .values_list('product_id', 'count')
    )
    max_product_orders = max(item_counts.values()) if item_counts else 1

    scored_products = []
    for p in products_list:
        store = scored_stores_map.get(p.store_id)
        store_score = store.relevance_score if store else 0.5
        
        # Product popularity log-scaled
        orders_count = item_counts.get(p.id, 0)
        prod_pop = math.log1p(orders_count) / max(math.log1p(max_product_orders), 1.0)
        
        # Product Text match scoring
        prod_text = 1.0
        if q:
            q_lower = q.lower().strip()
            prod_name_lower = p.name.lower()
            prod_desc_lower = p.description.lower() if p.description else ''
            if prod_name_lower == q_lower:
                prod_text = 1.0  # Exact name match
            elif q_lower in prod_name_lower:
                prod_text = 0.8  # Name substring match
            elif q_lower in prod_desc_lower:
                prod_text = 0.4  # Description match
            else:
                prod_text = 0.1

        # Calculate final blend
        p.relevance_score = round(0.50 * store_score + 0.20 * prod_pop + 0.30 * prod_text, 3)
        p.distance_km = getattr(store, 'distance_km', None) if store else None
        scored_products.append(p)

    scored_products.sort(key=lambda p: p.relevance_score, reverse=True)
    return scored_products
