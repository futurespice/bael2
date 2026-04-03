from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0013_backfill_debtpayment_store'),
        ('stores', '0012_alter_store_approval_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='debtpayment',
            name='store',
            field=models.ForeignKey(
                help_text='Магазин, по которому погашается долг',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='debt_payments',
                to='stores.store',
                verbose_name='Магазин',
            ),
        ),
    ]
