# Generated migration for adding notes field to StoreOrder

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_add_order_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='storeorder',
            name='notes',
            field=models.TextField(
                blank=True,
                verbose_name='Примечания к заказу',
                help_text='Дополнительные примечания (используется в ручных заказах)'
            ),
        ),
    ]
