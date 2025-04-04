# Generated by Django 5.1.6 on 2025-04-01 16:23

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0022_overtimepayment'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='overtimepayment',
            options={'ordering': ['-paid_date', 'employee'], 'verbose_name': 'Überstunden-Auszahlung', 'verbose_name_plural': 'Überstunden-Auszahlungen'},
        ),
        migrations.RenameField(
            model_name='overtimepayment',
            old_name='hours',
            new_name='hours_for_payment',
        ),
        migrations.AlterUniqueTogether(
            name='overtimepayment',
            unique_together={('employee', 'paid_date')},
        ),
        migrations.RemoveField(
            model_name='overtimepayment',
            name='month',
        ),
        migrations.RemoveField(
            model_name='overtimepayment',
            name='year',
        ),
    ]
