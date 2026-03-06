import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from stores.models import Store, KitchenSettings, Table
from catalog.models import Category, Product, Ingredient, InventoryStock
from orders.models import Order, OrderItem
from django.utils import timezone

User = get_user_model()

def seed():
    print("Clearing database...")
    User.objects.all().delete()
    Store.objects.all().delete()

    print("Creating users...")
    admin = User.objects.create_superuser('admin', 'admin@example.com', 'password', role=User.Role.ADMIN)
    seller = User.objects.create_user('seller1', 'seller1@example.com', 'password', role=User.Role.SELLER)
    customer = User.objects.create_user('customer1', 'customer1@example.com', 'password', role=User.Role.CUSTOMER)

    print("Creating store and settings...")
    store = Store.objects.create(owner=seller, name="Pizza Palace", location="123 Main St")
    KitchenSettings.objects.create(store=store, max_concurrent_prep_slots=5)

    print("Creating tables...")
    t1 = Table.objects.create(store=store, number="101", capacity=2)
    t2 = Table.objects.create(store=store, number="102", capacity=2)
    t3 = Table.objects.create(store=store, number="201", capacity=4)
    t4 = Table.objects.create(store=store, number="202", capacity=4)
    t5 = Table.objects.create(store=store, number="301", capacity=6)
    t6 = Table.objects.create(store=store, number="VIP-1", capacity=8)

    print("Creating catalog categories...")
    cat_starters = Category.objects.create(store=store, name="Starters")
    cat_pizza = Category.objects.create(store=store, name="Pizzas")
    cat_pasta = Category.objects.create(store=store, name="Pastas")
    cat_drinks = Category.objects.create(store=store, name="Beverages")
    cat_desserts = Category.objects.create(store=store, name="Desserts")

    print("Creating products...")
    # Instant Items
    coke = Product.objects.create(store=store, category=cat_drinks, name="Coca Cola", description="Chilled Coke can", price=2.00, requires_inventory=True, requires_kitchen=False)
    InventoryStock.objects.create(product=coke, quantity=100, low_stock_threshold=20)
    
    water = Product.objects.create(store=store, category=cat_drinks, name="Mineral Water", description="Bottled water 500ml", price=1.50, requires_inventory=True, requires_kitchen=False)
    InventoryStock.objects.create(product=water, quantity=150, low_stock_threshold=30)
    
    beer = Product.objects.create(store=store, category=cat_drinks, name="Craft Beer", description="Local IPA", price=5.50, requires_inventory=True, requires_kitchen=False)
    InventoryStock.objects.create(product=beer, quantity=50, low_stock_threshold=10)

    tiramisu = Product.objects.create(store=store, category=cat_desserts, name="Tiramisu", description="Classic Italian dessert (ready in fridge)", price=6.50, requires_inventory=True, requires_kitchen=False)
    InventoryStock.objects.create(product=tiramisu, quantity=20, low_stock_threshold=5)

    # Prep Items (Kitchen required)
    garlic_bread = Product.objects.create(store=store, category=cat_starters, name="Garlic Bread", description="Toasted with garlic butter and herbs", price=4.50, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=8)
    bruschetta = Product.objects.create(store=store, category=cat_starters, name="Bruschetta", description="Tomato, basil, balsamic on crostini", price=5.50, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=10)

    margherita = Product.objects.create(store=store, category=cat_pizza, name="Margherita Pizza", description="Classic cheese, tomato, fresh basil", price=10.00, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=15)
    pepperoni = Product.objects.create(store=store, category=cat_pizza, name="Pepperoni Pizza", description="Spicy pepperoni, mozzarella", price=12.00, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=18)
    hawaiian = Product.objects.create(store=store, category=cat_pizza, name="Hawaiian Pizza", description="Ham and pineapple", price=13.00, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=18)
    veggie = Product.objects.create(store=store, category=cat_pizza, name="Veggie Supreme", description="Peppers, onions, mushrooms, olives", price=12.50, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=20)

    carbonara = Product.objects.create(store=store, category=cat_pasta, name="Spaghetti Carbonara", description="Pancetta, egg, parmesan sauce", price=14.00, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=12)
    bolognese = Product.objects.create(store=store, category=cat_pasta, name="Penne Bolognese", description="Rich beef ragu", price=13.50, requires_inventory=False, requires_kitchen=True, estimated_prep_time_minutes=15)


    print("Creating sample orders...")
    
    # Order 1: New Dine-in order (Created state)
    order1 = Order.objects.create(store=store, customer=customer, table=t3, state=Order.State.CREATED, fulfillment_mode=Order.FulfillmentMode.DINE_IN, total_amount=40.50)
    OrderItem.objects.create(order=order1, product=garlic_bread, quantity=1, unit_price=4.50)
    OrderItem.objects.create(order=order1, product=pepperoni, quantity=2, unit_price=12.00)
    OrderItem.objects.create(order=order1, product=coke, quantity=3, unit_price=2.00)
    OrderItem.objects.create(order=order1, product=beer, quantity=1, unit_price=5.50)
    OrderItem.objects.create(order=order1, product=water, quantity=1, unit_price=1.50)

    # Order 2: Takeaway order currently preparing in kitchen
    order2 = Order.objects.create(store=store, customer=customer, state=Order.State.PREPARING, fulfillment_mode=Order.FulfillmentMode.TAKEAWAY, total_amount=24.50)
    OrderItem.objects.create(order=order2, product=margherita, quantity=1, unit_price=10.00, is_ready=False)
    OrderItem.objects.create(order=order2, product=carbonara, quantity=1, unit_price=14.00, is_ready=False)
    
    # Order 3: Dine-in order mostly ready
    order3 = Order.objects.create(store=store, customer=customer, table=t1, state=Order.State.PREPARING, fulfillment_mode=Order.FulfillmentMode.DINE_IN, total_amount=27.50)
    OrderItem.objects.create(order=order3, product=bruschetta, quantity=1, unit_price=5.50, is_ready=True) # Appetizer is ready
    OrderItem.objects.create(order=order3, product=veggie, quantity=1, unit_price=12.50, is_ready=False) # Main still cooking
    OrderItem.objects.create(order=order3, product=water, quantity=2, unit_price=1.50, is_ready=True) # Drinks are ready
    OrderItem.objects.create(order=order3, product=tiramisu, quantity=1, unit_price=6.50, is_ready=True) # Dessert ready

    # Order 4: Completed order from earlier today
    order4 = Order.objects.create(store=store, customer=customer, state=Order.State.COMPLETED, fulfillment_mode=Order.FulfillmentMode.TAKEAWAY, total_amount=13.00)
    OrderItem.objects.create(order=order4, product=hawaiian, quantity=1, unit_price=13.00, is_ready=True)

    # Order 5: Awaiting payment order
    order5 = Order.objects.create(store=store, customer=customer, table=t6, state=Order.State.AWAITING_PAYMENT, fulfillment_mode=Order.FulfillmentMode.DINE_IN, total_amount=27.00)
    OrderItem.objects.create(order=order5, product=bolognese, quantity=2, unit_price=13.50)

    print("Database seeding completed successfully.")

if __name__ == "__main__":
    seed()
