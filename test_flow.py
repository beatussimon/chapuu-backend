import requests
import json
import datetime
from django.utils import timezone

BASE_URL = "http://127.0.0.1:8000/api"

res = requests.post(f"{BASE_URL}/token/", json={"username": "customer_test", "password": "password123"})
if res.status_code != 200:
    print("Login failed, please create a customer1 user or change credentials.")
    exit(1)
token = res.json()['access']
headers = {"Authorization": f"Bearer {token}"}

# 1. Get stores
res = requests.get(f"{BASE_URL}/stores/")
stores = res.json()
if not stores:
    print("No stores found, test aborted.")
    exit(1)
store_id = stores[0]['id']

# 2. Get a product
res = requests.get(f"{BASE_URL}/products/")
products = res.json()
if not products:
    print("No products found, test aborted.")
    exit(1)
product = products[0]

# 3. Create Reservation
dt = timezone.now() + datetime.timedelta(days=1)
res_payload = {
    "store": store_id,
    "reservation_time": dt.isoformat(),
    "duration_minutes": 60,
    "guest_count": 2
}
res = requests.post(f"{BASE_URL}/reservations/", json=res_payload, headers=headers)
print("Reservation Response:", res.status_code, res.json())

if res.status_code != 201:
    exit(1)
    
reservation_id = res.json()['id']

# 4. Create Order linked to Reservation
order_payload = {
    "store": store_id,
    "fulfillment_mode": "RESERVATION",
    "reservation": reservation_id,
    "items": [
        {
            "product": product['id'],
            "quantity": 2,
            "unit_price": product['price']
        }
    ]
}
res = requests.post(f"{BASE_URL}/orders/", json=order_payload, headers=headers)
print("Order Response:", res.status_code, res.json())
