import math

def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in km between two coordinates using Haversine formula."""
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    except (TypeError, ValueError):
        return None
    
    R = 6371.0  # Radius of the earth in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def annotate_distances(queryset, lat, lng):
    """Add distance_km attribute to each store. Returns list of store objects sorted by distance."""
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        # Fallback if coordinates are invalid or not provided
        for store in queryset:
            store.distance_km = None
        return list(queryset)

    results = []
    others = []
    for store in queryset:
        if store.latitude is not None and store.longitude is not None:
            dist = haversine_km(lat, lng, store.latitude, store.longitude)
            if dist is not None:
                store.distance_km = round(dist, 2)
                results.append(store)
            else:
                store.distance_km = None
                others.append(store)
        else:
            store.distance_km = None
            others.append(store)
    
    results.sort(key=lambda s: s.distance_km)
    # Combine sorted stores with those that don't have location set
    return results + others

def filter_by_radius(stores_with_distance, radius_km):
    """Filter pre-annotated stores by radius."""
    try:
        radius_km = float(radius_km)
    except (TypeError, ValueError):
        return stores_with_distance
    return [s for s in stores_with_distance if s.distance_km is not None and s.distance_km <= radius_km]
