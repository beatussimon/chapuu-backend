import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'adminpass')
    print("Created admin.")
else:
    print("Admin already exists. Fixing password if incorrect.")
    u = User.objects.get(username='admin')
    u.set_password('adminpass')
    u.save()
    print("Reset admin password.")
