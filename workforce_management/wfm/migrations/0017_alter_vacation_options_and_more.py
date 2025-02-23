# Generated by Django 5.1.6 on 2025-02-23 18:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0016_closureday'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='vacation',
            options={},
        ),
        migrations.RemoveField(
            model_name='vacationentitlement',
            name='total_days',
        ),
        migrations.AddField(
            model_name='vacationentitlement',
            name='total_hours',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name='vacation',
            name='end_date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='vacation',
            name='notes',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='vacation',
            name='start_date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='vacation',
            name='status',
            field=models.CharField(choices=[('REQUESTED', 'Beantragt'), ('APPROVED', 'Genehmigt'), ('REJECTED', 'Abgelehnt')], default='REQUESTED', max_length=10),
        ),
        migrations.AlterField(
            model_name='vacationentitlement',
            name='year',
            field=models.IntegerField(),
        ),
    ]
