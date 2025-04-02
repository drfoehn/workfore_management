# Generated by Django 5.1.6 on 2025-04-02 08:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0023_alter_overtimepayment_options_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='overtimepayment',
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name='overtimepayment',
            name='hours_for_payment',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]
