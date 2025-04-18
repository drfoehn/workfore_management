# Generated by Django 5.1.6 on 2025-03-13 19:34

import datetime
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0004_remove_therapistbooking_payment_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduletemplate',
            name='break_duration',
            field=models.DurationField(blank=True, default=datetime.timedelta(0), null=True, verbose_name='Pause'),
        ),
        migrations.AlterField(
            model_name='therapistscheduletemplate',
            name='therapist',
            field=models.ForeignKey(limit_choices_to={'role': 'THERAPIST'}, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='Therapeut'),
        ),
    ]
