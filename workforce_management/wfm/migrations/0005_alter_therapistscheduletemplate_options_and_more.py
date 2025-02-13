# Generated by Django 5.1.6 on 2025-02-13 18:51

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0004_therapistscheduletemplate'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='therapistscheduletemplate',
            options={'ordering': ['weekday', 'start_time']},
        ),
        migrations.AlterUniqueTogether(
            name='therapistscheduletemplate',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='therapistscheduletemplate',
            name='hours',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=4),
        ),
        migrations.AlterField(
            model_name='therapistscheduletemplate',
            name='end_time',
            field=models.TimeField(),
        ),
        migrations.AlterField(
            model_name='therapistscheduletemplate',
            name='start_time',
            field=models.TimeField(),
        ),
        migrations.AlterField(
            model_name='therapistscheduletemplate',
            name='therapist',
            field=models.ForeignKey(limit_choices_to={'role': 'THERAPIST'}, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='therapistscheduletemplate',
            name='weekday',
            field=models.IntegerField(choices=[(0, 'Montag'), (1, 'Dienstag'), (2, 'Mittwoch'), (3, 'Donnerstag'), (4, 'Freitag'), (5, 'Samstag'), (6, 'Sonntag')]),
        ),
    ]
