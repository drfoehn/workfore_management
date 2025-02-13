# Generated by Django 5.1.6 on 2025-02-13 19:03

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0005_alter_therapistscheduletemplate_options_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='therapistbooking',
            options={'ordering': ['date', 'start_time']},
        ),
        migrations.RemoveField(
            model_name='therapistbooking',
            name='created_at',
        ),
        migrations.RemoveField(
            model_name='therapistbooking',
            name='updated_at',
        ),
        migrations.AddField(
            model_name='therapistbooking',
            name='hours',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4),
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='actual_hours',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True),
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='end_time',
            field=models.TimeField(),
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='notes',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='start_time',
            field=models.TimeField(),
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='status',
            field=models.CharField(choices=[('RESERVED', 'Reserviert'), ('USED', 'Verwendet'), ('CANCELLED', 'Storniert')], default='RESERVED', max_length=10),
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='therapist',
            field=models.ForeignKey(limit_choices_to={'role': 'THERAPIST'}, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]
