from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from stores.models import Store, KitchenSettings, CurrencyConfig

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database additively and safely without wiping any existing tables.'

    def handle(self, *args, **kwargs):
        self.stdout.write('Additive Seeding...')
        password = 'password123'
        
        # 1. Superuser
        superuser, created = User.objects.get_or_create(
            username='superuser',
            defaults={
                'email': 'superuser@example.com',
                'role': 'SUPERUSER',
                'is_superuser': True,
                'is_staff': True
            }
        )
        if created or not superuser.check_password(password):
            superuser.set_password(password)
            superuser.role = 'SUPERUSER'
            superuser.is_superuser = True
            superuser.is_staff = True
            superuser.save()
            self.stdout.write('Superuser created or password updated.')

        # 2. Admin
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@example.com',
                'role': 'ADMIN',
                'is_staff': True
            }
        )
        if created or not admin_user.check_password(password):
            admin_user.set_password(password)
            admin_user.role = 'ADMIN'
            admin_user.is_staff = True
            admin_user.save()
            self.stdout.write('Admin user created or password updated.')

        # 3. Seller
        seller, created = User.objects.get_or_create(
            username='seller1',
            defaults={
                'email': 'seller1@example.com',
                'role': 'SELLER'
            }
        )
        if created or not seller.check_password(password):
            seller.set_password(password)
            seller.role = 'SELLER'
            seller.save()
            self.stdout.write('Seller user created or password updated.')

        # 4. Customer
        customer, created = User.objects.get_or_create(
            username='customer1',
            defaults={
                'email': 'customer1@example.com',
                'role': 'CUSTOMER'
            }
        )
        if created or not customer.check_password(password):
            customer.set_password(password)
            customer.role = 'CUSTOMER'
            customer.save()
            self.stdout.write('Customer user created or password updated.')

        # 5. Store
        store, created = Store.objects.get_or_create(
            name='Pizza Palace',
            defaults={
                'location': '123 Main St',
                'owner': seller,
                'store_type': 'RESTAURANT',
                'is_active': True
            }
        )
        if created:
            self.stdout.write('Store created.')
        else:
            # Update fields safely if needed
            store.owner = seller
            store.store_type = 'RESTAURANT'
            store.is_active = True
            store.save()

        # 6. Kitchen Settings
        kitchen_settings, created = KitchenSettings.objects.get_or_create(
            store=store,
            defaults={
                'max_concurrent_prep_slots': 5,
                'is_kitchen_paused': False,
                'auto_approve_orders': True
            }
        )
        if created:
            self.stdout.write('Kitchen settings created.')

        # 7. Currency Config
        currency, created = CurrencyConfig.objects.get_or_create(
            code='TZS',
            defaults={
                'name': 'Tanzanian Shilling',
                'symbol': 'TSh',
                'rate_to_base': 1.0,
                'is_default': True,
                'is_active': True
            }
        )
        if created:
            self.stdout.write('Currency config created.')

        self.stdout.write(self.style.SUCCESS('Database Safe Additive Seed Completed Successfully!'))

