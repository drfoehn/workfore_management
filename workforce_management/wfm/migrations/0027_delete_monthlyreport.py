# Generated by Django 5.1.6 on 2025-04-06 08:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0026_alter_overtimeaccount_unique_together_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='MonthlyReport',
        ),
    ]
