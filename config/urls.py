"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from catalog.views import ProductViewSet, CategoryViewSet, InventoryStockViewSet, IngredientViewSet, RecipeIngredientViewSet
from users.views import UserViewSet, CustomerRegistrationView, CurrentUserView
from orders.views import OrderViewSet
from catalog.stats_views import BillboardStatsViewSet
from catalog.analytics_seller_views import SellerAnalyticsViewSet
from stores.views import StoreViewSet, AdvertisementViewSet, CurrencyConfigViewSet, TableViewSet, NoticeViewSet, StorePaymentMethodViewSet
from reservations.views import ReservationViewSet, TableSessionViewSet
from reviews.views import StoreReviewViewSet
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.db import connection
from django.shortcuts import redirect
from users.throttles import LoginRateThrottle

def root_redirect(request):
    return redirect('/api/')

def favicon_view(request):
    return redirect('/media/chapuu_assets/chapuu_brand.png')

def health_check(request):
    db_ok = True
    redis_ok = True
    try:
        connection.ensure_connection()
    except Exception:
        db_ok = False
    try:
        from django.core.cache import cache
        cache.set('health_ping', 'pong', 10)
        redis_ok = cache.get('health_ping') == 'pong'
    except Exception:
        redis_ok = False
    status_code = 200 if db_ok and redis_ok else 503
    return JsonResponse({'status': 'ok' if status_code == 200 else 'degraded', 'db': db_ok, 'redis': redis_ok}, status=status_code)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'inventory', InventoryStockViewSet, basename='inventory')
router.register(r'ingredients', IngredientViewSet, basename='ingredient')
router.register(r'recipes', RecipeIngredientViewSet, basename='recipe')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'stores', StoreViewSet, basename='store')
router.register(r'reservations', ReservationViewSet, basename='reservation')
router.register(r'sessions', TableSessionViewSet, basename='session')
router.register(r'users', UserViewSet, basename='user')
router.register(r'reviews', StoreReviewViewSet, basename='review')
router.register(r'ads', AdvertisementViewSet, basename='ad')
router.register(r'stats/billboard', BillboardStatsViewSet, basename='billboard')
router.register(r'analytics/seller', SellerAnalyticsViewSet, basename='seller-analytics')
router.register(r'currencies', CurrencyConfigViewSet, basename='currency')
router.register(r'tables', TableViewSet, basename='table')
router.register(r'notices', NoticeViewSet, basename='notice')
router.register(r'payment-methods', StorePaymentMethodViewSet, basename='payment-method')

urlpatterns = [
    path('', root_redirect),
    path('favicon.ico', favicon_view),
    path(settings.ADMIN_URL, admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(throttle_classes=[LoginRateThrottle]), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/register/', CustomerRegistrationView.as_view(), name='api_register'),
    path('api/auth/users/me/', CurrentUserView.as_view(), name='current_user'),
    path('api/health/', health_check, name='health'),
    path('api/', include(router.urls)),
]

# Always serve media files (required for image uploads to work)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

