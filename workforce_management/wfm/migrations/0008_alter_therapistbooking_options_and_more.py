# Generated by Django 5.1.6 on 2025-02-15 16:18

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0007_customuser_color'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='therapistbooking',
            options={},
        ),
        migrations.RemoveField(
            model_name='therapistbooking',
            name='hours',
        ),
        migrations.AlterField(
            model_name='therapistbooking',
            name='therapist',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]
