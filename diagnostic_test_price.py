import os
import django
from decimal import Decimal

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from catalog.models import Product
    from catalog.serializers import ProductSerializer
    from stores.models import Store

    # Retrieve an existing store
    store = Store.objects.first()
    if not store:
        print("No store found!")
        exit(1)

    print(f"Using store: {store.name} (ID: {store.id})")

    # Programmatically test serialization and saving of price 500
    data = {
        'store': store.id,
        'name': 'Test Price Saving 500',
        'price': '500.00',
        'requires_kitchen': True,
        'is_active': True
    }

    serializer = ProductSerializer(data=data)
    if serializer.is_valid():
        product = serializer.save()
        print(f"Product saved via serializer! ID: {product.id}, Name: {product.name}, Stored Price: {product.price} (Type: {type(product.price)})")
        
        # Clean up
        product.delete()
        print("Test product cleaned up.")
    else:
        print("Serializer errors:", serializer.errors)
