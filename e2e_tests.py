import requests

BASE_URL = 'http://127.0.0.1:8000/api'

def run_tests():
    print("--- STARTING E2E API TESTS ---")
    
    # 1. Customer Login
    print("1. Logging in as Customer...")
    resp = requests.post(f"{BASE_URL}/token/", json={"username": "customer1", "password": "password"})
    if resp.status_code != 200:
        print("FAIL: Customer login failed.", resp.text)
        return
    customer_token = resp.json()['access']
    headers_cust = {'Authorization': f'Bearer {customer_token}'}
    print("PASS: Customer logged in.")

    # 2. Fetch Products
    print("2. Fetching Catalog Products...")
    resp = requests.get(f"{BASE_URL}/products/", headers=headers_cust)
    if resp.status_code != 200:
        print("FAIL: Failed to fetch products.", resp.text)
        return
    products = resp.json()
    print(f"PASS: Fetched {len(products)} products.")
    
    # Get a specific product
    pizza_id = products[0]['id'] if products else None
    if not pizza_id:
        print("FAIL: No active products found.")
        return

    # 3. Fetch Tables
    print("3. Fetching Store Tables...")
    resp = requests.get(f"{BASE_URL}/stores/1/tables/", headers=headers_cust)
    if resp.status_code != 200:
        print("FAIL: Failed to fetch tables.", resp.text)
        return
    tables = resp.json()
    print(f"PASS: Fetched {len(tables)} tables.")
    table_id = tables[0]['id']

    # 4. Place Order
    print("4. Placing New Order...")
    order_payload = {
        "store": 1,
        "fulfillment_mode": "DINE_IN",
        "table": table_id,
        "items": [
            {"product": pizza_id, "quantity": 1, "unit_price": 10.0}
        ]
    }
    resp = requests.post(f"{BASE_URL}/orders/", json=order_payload, headers=headers_cust)
    if resp.status_code != 201:
        print("FAIL: Order creation failed.", resp.text)
        return
    order_data = resp.json()
    order_id = order_data['id']
    order_item_id = order_data['items'][0]['id']
    print(f"PASS: Order created with ID {order_id} (State: {order_data['state']}).")

    # 4.5 Simulate Webhook Payment
    print("4.5 Simulating Zenopay Webhook...")
    webhook_payload = {
        "transaction_id": "e2e_mock_tx_001",
        "status": "COMPLETED",
        "order_id": order_id
    }
    resp = requests.post(f"{BASE_URL}/webhook/zenopay/", json=webhook_payload)
    if resp.status_code != 200:
        print("FAIL: Webhook processing failed. Writing error to e2e_error.html")
        with open("e2e_error.html", "w") as f:
            f.write(resp.text)
        return
    print("PASS: Webhook processed successfully. Order should now be PAID & QUEUED.")

    # 5. Seller Login
    print("5. Logging in as Seller...")
    resp = requests.post(f"{BASE_URL}/token/", json={"username": "seller1", "password": "password"})
    if resp.status_code != 200:
        print("FAIL: Seller login failed.", resp.text)
        return
    seller_token = resp.json()['access']
    headers_seller = {'Authorization': f'Bearer {seller_token}'}
    print("PASS: Seller logged in.")

    # 6. Fetch Orders as Seller
    print("6. Fetching Orders for Kitchen Queue...")
    resp = requests.get(f"{BASE_URL}/orders/", headers=headers_seller)
    if resp.status_code != 200:
        print("FAIL: Failed to fetch orders.", resp.text)
        return
    orders = resp.json()
    found = any(o['id'] == order_id for o in orders)
    print(f"PASS: Order found in queue: {found}.")

    # 7. Mark Item Ready
    print(f"7. Marking item {order_item_id} ready...")
    resp = requests.post(f"{BASE_URL}/orders/{order_id}/items/{order_item_id}/ready/", headers=headers_seller)
    if resp.status_code != 200:
        print("FAIL: Failed to mark item ready.", resp.status_code, resp.text)
    else:
        print("PASS: Item marked ready.")

    # 8. Customer Books a Reservation
    print("8. Customer Booking a Reservation...")
    from datetime import datetime
    import datetime as dt
    tomorrow = (datetime.now() + dt.timedelta(days=1)).strftime("%Y-%m-%dT19:00:00Z")
    
    res_payload = {
        "store": 1,
        "reservation_time": tomorrow,
        "duration_minutes": 60,
        "guest_count": 2
    }
    resp = requests.post(f"{BASE_URL}/reservations/", json=res_payload, headers=headers_cust)
    if resp.status_code != 201:
        print("FAIL: Reservation creation failed.", resp.status_code, resp.text)
    else:
        res_id = resp.json()['id']
        print(f"PASS: Reservation created with ID {res_id}.")

        # 9. Seller Confirms Reservation
        print("9. Seller Confirming Reservation...")
        resp = requests.post(f"{BASE_URL}/reservations/{res_id}/confirm/", headers=headers_seller)
        if resp.status_code != 200:
            print("FAIL: Reservation confirmation failed.", resp.text)
        else:
            print("PASS: Reservation confirmed.")

            # 10. Seller Checks In Reservation
            print("10. Seller Checking-in to active Table Session...")
            resp = requests.post(f"{BASE_URL}/reservations/{res_id}/check_in/", headers=headers_seller)
            if resp.status_code != 200:
                print("FAIL: Check-in failed.", resp.text)
            else:
                session_id = resp.json().get('session_id')
                print(f"PASS: Customer seated. Active Table Session {session_id} created!")

    # 11. Seller Checks and Adjusts Inventory
    print("11. Seller checking and adjusting Inventory...")
    resp = requests.get(f"{BASE_URL}/inventory/", headers=headers_seller)
    if resp.status_code != 200:
        print("FAIL: Failed to fetch inventory.", resp.text)
    else:
        inventory_items = resp.json()
        print(f"PASS: Fetched {len(inventory_items)} inventory items.")
        if inventory_items:
            # Let's add +10 to the first tracked inventory item
            first_inv = inventory_items[0]
            start_qty = float(first_inv['quantity'])
            resp = requests.post(f"{BASE_URL}/inventory/{first_inv['id']}/adjust/", json={"adjustment": 10}, headers=headers_seller)
            if resp.status_code != 200:
                print("FAIL: Failed to adjust inventory.", resp.text)
            else:
                new_qty = float(resp.json()['new_quantity'])
                print(f"PASS: Adjusted inventory from {start_qty} to {new_qty} successfully.")

    # 12. Seller Toggles Product Availability
    print("12. Seller toggling product availability (Out of Stock)...")
    if pizza_id:
        resp = requests.post(f"{BASE_URL}/products/{pizza_id}/toggle_status/", headers=headers_seller)
        if resp.status_code != 200:
            print("FAIL: Failed to toggle product.", resp.text)
        else:
            is_active = resp.json()['is_active']
            state_str = "Active" if is_active else "Out-of-Stock"
            print(f"PASS: Toggled Product #{pizza_id} state to: {state_str}")

    # 13. Admin Flow
    print("13. Logging in as Admin...")
    resp = requests.post(f"{BASE_URL}/token/", json={"username": "admin", "password": "adminpass"})
    if resp.status_code != 200:
        print("FAIL: Admin login failed.", resp.text)
    else:
        admin_token = resp.json()['access']
        headers_admin = {'Authorization': f'Bearer {admin_token}'}
        print("PASS: Admin logged in.")

        print("13b. Admin creating a new Seller Account...")
        resp = requests.post(f"{BASE_URL}/users/", json={"username": "newseller99", "password": "password", "role": "SELLER", "phone_number": "555-0100"}, headers=headers_admin)
        if resp.status_code != 201:
            print("FAIL: Admin failed to create seller.", resp.text)
        else:
            new_seller_id = resp.json()['id']
            print(f"PASS: Admin successfully minted Seller Account #{new_seller_id}.")

            print("13c. Admin provisioning a new Store Instance...")
            resp = requests.post(f"{BASE_URL}/stores/", json={"name": "The Golden Crust", "address": "123 Beta Way", "owner": new_seller_id, "is_active": True}, headers=headers_admin)
            if resp.status_code != 201:
                print("FAIL: Admin failed to provision Store.", resp.text)
            else:
                new_store_id = resp.json()['id']
                print(f"PASS: Admin successfully provisioned Store #{new_store_id}!")

    print("--- E2E TESTS COMPLETED ---")

if __name__ == "__main__":
    run_tests()
