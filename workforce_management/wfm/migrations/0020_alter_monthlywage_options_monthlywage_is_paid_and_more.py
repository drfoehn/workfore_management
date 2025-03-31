# Generated by Django 5.1.6 on 2025-03-31 17:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0019_monthlywage'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='monthlywage',
            options={'ordering': ['-year', '-month', 'employee'], 'verbose_name': 'Monatliches Gehalt', 'verbose_name_plural': 'Monatliche Gehälter'},
        ),
        migrations.AddField(
            model_name='monthlywage',
            name='is_paid',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='monthlywage',
            name='paid_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
