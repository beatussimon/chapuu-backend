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
from stores.views import StoreViewSet, AdvertisementViewSet, CurrencyConfigViewSet, TableViewSet, NoticeViewSet
from reservations.views import ReservationViewSet, TableSessionViewSet
from payments.views import ZenopayWebhookView
from reviews.views import StoreReviewViewSet
from django.conf import settings
from django.conf.urls.static import static

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

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/register/', CustomerRegistrationView.as_view(), name='api_register'),
    path('api/auth/users/me/', CurrentUserView.as_view(), name='current_user'),
    path('api/', include(router.urls)),
    path('api/webhook/zenopay/', ZenopayWebhookView.as_view(), name='zenopay-webhook'),
]

# Always serve media files (required for image uploads to work)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

