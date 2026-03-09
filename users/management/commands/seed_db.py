from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from stores.models import Store, KitchenSettings, CurrencyConfig
from django.db import connection

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with robust user and store data.'

    def handle(self, *args, **kwargs):
        self.stdout.write('Atomic Clearing and Seeding...')
        
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA foreign_keys = OFF;')
            tables = [
                'orders_orderitem', 'orders_ordereventlog', 'orders_order', 
                'reservations_tablesession', 'reservations_reservation', 
                'catalog_inventorystock', 'catalog_product', 'catalog_category', 
                'stores_table', 'stores_kitchensettings', 'stores_currencyconfig', 
                'stores_store', 'users_user'
            ]
            for table in tables:
                cursor.execute(f'DELETE FROM {table}')
            cursor.execute('PRAGMA foreign_keys = ON;')

        # 2. Create Users with verified password 'password123'
        password = 'password123'
        
        # Admin
        User.objects.create_superuser(
            id=1,
            username='admin', 
            email='admin@example.com', 
            password=password,
            role='ADMIN'
        )
        
        # Seller
        seller = User.objects.create_user(
            id=2,
            username='seller1', 
            email='seller1@example.com', 
            password=password,
            role='SELLER'
        )
        
        # Customer
        User.objects.create_user(
            id=3,
            username='customer1', 
            email='customer1@example.com', 
            password=password,
            role='CUSTOMER'
        )

        # 3. Create Store
        store = Store.objects.create(
            id=1,
            name='Pizza Palace',
            location='123 Main St',
            owner=seller,
            store_type='RESTAURANT',
            is_active=True
        )
        
        KitchenSettings.objects.create(
            store=store,
            max_concurrent_prep_slots=5,
            is_kitchen_paused=False,
            auto_approve_orders=True
        )

        # 4. Create Currency
        CurrencyConfig.objects.create(
            code='TZS',
            name='Tanzanian Shilling',
            symbol='TSh',
            rate_to_base=1.0,
            is_default=True,
            is_active=True
        )

        self.stdout.write(self.style.SUCCESS('Database Re-Seeded Successfully!'))
