from django.db import migrations, models
from django.conf import settings

class Migration(migrations.Migration):

    dependencies = [
        ('stores', '0009_alter_store_store_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='notice',
            name='read_by',
            field=models.ManyToManyField(blank=True, related_name='read_notices', to=settings.AUTH_USER_MODEL),
        ),
    ]
