import os
import django

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

    from rest_framework.test import APIClient
    from catalog.models import Product
    from stores.models import Store
    from users.models import User

    # Find the seller user
    user = User.objects.get(username='seller1')
    store = Store.objects.first()

    client = APIClient()
    client.force_authenticate(user=user)

    data = {
        'store': store.id,
        'name': 'HTTP Test Price 500',
        'price': '500.00',
        'requires_kitchen': True,
        'is_active': True
    }

    print("Sending POST request to /api/products/ ...")
    response = client.post('/api/products/', data, format='json')
    print("Response status code:", response.status_code)
    print("Response data:", response.data)

    if response.status_code == 201:
        # Retrieve the product from database
        product_id = response.data['id']
        product = Product.objects.get(id=product_id)
        print(f"Product saved! Stored Price in DB: {product.price} (Type: {type(product.price)})")
        
        # Clean up
        product.delete()
        print("HTTP test product cleaned up.")
    else:
        print("Failed to create product via HTTP POST.")
