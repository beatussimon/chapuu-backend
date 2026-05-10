from django.urls import re_path
from orders import consumers

websocket_urlpatterns = [
    re_path(r'^/?ws/order/(?P<order_id>\d+)/$', consumers.OrderConsumer.as_asgi()),
    re_path(r'^/?ws/orders/(?P<store_id>[^/]+)/$', consumers.OrderConsumer.as_asgi()),
    re_path(r'^/?ws/orders/$', consumers.OrderConsumer.as_asgi()),
]