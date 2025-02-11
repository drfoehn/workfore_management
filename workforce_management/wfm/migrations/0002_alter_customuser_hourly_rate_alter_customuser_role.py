# Generated by Django 5.1.6 on 2025-02-11 20:59

import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='hourly_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], verbose_name='Stundenlohn'),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(choices=[('OWNER', 'Ordinationsinhaber/in'), ('EMPLOYEE', 'Mitarbeiter/in')], default='EMPLOYEE', max_length=10),
        ),
    ]
