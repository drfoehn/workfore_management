# Generated by Django 5.1.6 on 2025-03-08 08:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0031_remove_therapistbooking_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='therapistbooking',
            name='hours',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True),
        ),
    ]
