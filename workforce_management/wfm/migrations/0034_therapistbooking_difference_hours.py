# Generated by Django 5.1.6 on 2025-03-08 08:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0033_alter_therapistscheduletemplate_hours'),
    ]

    operations = [
        migrations.AddField(
            model_name='therapistbooking',
            name='difference_hours',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Differenz zwischen geplanten und tatsächlichen Stunden', max_digits=4, null=True, verbose_name='Stundendifferenz'),
        ),
    ]
