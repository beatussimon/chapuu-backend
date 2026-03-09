import sqlite3
from datetime import datetime
import uuid
import os

db_path = os.path.join(os.path.dirname(__file__), 'db.sqlite3')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

def insert_user(id, username, email, role):
    # Valid Django PBKDF2 hash for 'password123' generated on this machine
    valid_hash = 'pbkdf2_sha256$1000000$5JV9saQvbRXuWc23rZZew3$6r/Dn0RjSxQIB0VcMGsjLCpnppLYoKwOEXHCXs3xl5I='
    cursor.execute('INSERT OR IGNORE INTO users_user (id, password, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined, role, phone_number, loyalty_points) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', 
        (id, valid_hash, id==1, username, '', '', email, id==1, 1, datetime.now(), role, '', 0))

print('Clearing existing data...')
tables = ['orders_orderitem', 'orders_ordereventlog', 'orders_order', 'reservations_tablesession', 'reservations_reservation', 'catalog_inventorystock', 'catalog_product', 'catalog_category', 'stores_table', 'stores_kitchensettings', 'stores_currencyconfig', 'stores_store', 'users_user']
for table in tables:
    cursor.execute(f'DELETE FROM {table}')

print('Inserting users...')
insert_user(1, 'admin', 'admin@example.com', 'ADMIN')
insert_user(2, 'seller1', 'seller1@example.com', 'SELLER')
insert_user(3, 'customer1', 'customer1@example.com', 'CUSTOMER')

print('Inserting store...')
cursor.execute('INSERT INTO stores_store (id, name, location, owner_id, is_active, store_type, base_delivery_fee, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
    (1, 'Pizza Palace', '123 Main St', 2, 1, 'RESTAURANT', 0.0, datetime.now()))
cursor.execute('INSERT INTO stores_kitchensettings (id, max_concurrent_prep_slots, is_kitchen_paused, auto_approve_orders, store_id) VALUES (?, ?, ?, ?, ?)', (1, 5, 0, 1, 1))

print('Inserting tables...')
for i, (num, cap) in enumerate([('101', 2), ('102', 2), ('201', 4), ('202', 4), ('301', 6), ('VIP-1', 8)], 1):
    cursor.execute('INSERT INTO stores_table (id, number, capacity, is_active, store_id) VALUES (?, ?, ?, ?, ?)', (i, num, cap, 1, 1))

print('Inserting categories...')
for i, name in enumerate(['Starters', 'Pizzas', 'Pastas', 'Beverages', 'Desserts'], 1):
    cursor.execute('INSERT INTO catalog_category (id, name, store_id) VALUES (?, ?, ?)', (i, name, 1))

print('Inserting products...')
products = [
    (1, 'Coca Cola', 'Chilled Coke can', 2.00, 1, 0, 4, 1, 0, 1, datetime.now()),
    (2, 'Mineral Water', 'Bottled water 500ml', 1.50, 1, 0, 4, 1, 0, 1, datetime.now()),
    (3, 'Garlic Bread', 'Toasted with herbs', 4.50, 0, 1, 1, 1, 8, 1, datetime.now()),
    (4, 'Margherita Pizza', 'Cheese and tomato', 10.00, 0, 1, 2, 1, 15, 1, datetime.now()),
    (5, 'Pepperoni Pizza', 'Spicy pepperoni', 12.00, 0, 1, 2, 1, 18, 1, datetime.now()),
    (6, 'Spaghetti Carbonara', 'Creamy pasta', 14.00, 0, 1, 3, 1, 12, 1, datetime.now()),
]
for p in products:
    cursor.execute('INSERT INTO catalog_product (id, name, description, price, requires_inventory, requires_kitchen, category_id, store_id, estimated_prep_time_minutes, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', p)

print('Inserting inventory stocks...')
cursor.execute('INSERT INTO catalog_inventorystock (id, quantity, low_stock_threshold, product_id) VALUES (?, ?, ?, ?)', (1, 100, 20, 1))
cursor.execute('INSERT INTO catalog_inventorystock (id, quantity, low_stock_threshold, product_id) VALUES (?, ?, ?, ?)', (2, 150, 30, 2))

print('Inserting currencies...')
cursor.execute('INSERT INTO stores_currencyconfig (id, code, name, symbol, rate_to_base, is_default, is_active, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
    (1, 'TZS', 'Tanzanian Shilling', 'TSh', 1.0, 1, 1, datetime.now()))

print('Inserting orders...')
now = datetime.now()
# Order 1
cursor.execute('INSERT INTO orders_order (id, state, fulfillment_mode, total_amount, created_at, updated_at, customer_id, store_id, table_id, scheduled_time, customer_phone, delivery_location) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', 
    (1, 'CREATED', 'DINE_IN', 38.50, now, now, 3, 1, 3, None, '', ''))
cursor.execute('INSERT INTO orders_orderitem (id, quantity, unit_price, is_ready, order_id, product_id) VALUES (?, ?, ?, ?, ?, ?)', (1, 1, 4.50, 0, 1, 3))
cursor.execute('INSERT INTO orders_orderitem (id, quantity, unit_price, is_ready, order_id, product_id) VALUES (?, ?, ?, ?, ?, ?)', (2, 2, 12.00, 0, 1, 5))
cursor.execute('INSERT INTO orders_orderitem (id, quantity, unit_price, is_ready, order_id, product_id) VALUES (?, ?, ?, ?, ?, ?)', (3, 5, 2.00, 0, 1, 1))

# Order 2
cursor.execute('INSERT INTO orders_order (id, state, fulfillment_mode, total_amount, created_at, updated_at, customer_id, store_id, table_id, scheduled_time, customer_phone, delivery_location) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', 
    (2, 'PREPARING', 'TAKEAWAY', 24.00, now, now, 3, 1, None, None, '', ''))
cursor.execute('INSERT INTO orders_orderitem (id, quantity, unit_price, is_ready, order_id, product_id) VALUES (?, ?, ?, ?, ?, ?)', (4, 1, 10.00, 0, 2, 4))
cursor.execute('INSERT INTO orders_orderitem (id, quantity, unit_price, is_ready, order_id, product_id) VALUES (?, ?, ?, ?, ?, ?)', (5, 1, 14.00, 0, 2, 6))

conn.commit()
conn.close()
print('Raw SQL Injection Success!')
