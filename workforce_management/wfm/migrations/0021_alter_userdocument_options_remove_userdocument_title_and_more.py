# Generated by Django 5.1.6 on 2025-03-04 17:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wfm', '0020_alter_workinghours_options_workinghours_ist_hours_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='userdocument',
            options={'ordering': ['-uploaded_at'], 'verbose_name': 'Dokument', 'verbose_name_plural': 'Dokumente'},
        ),
        migrations.RemoveField(
            model_name='userdocument',
            name='title',
        ),
        migrations.AddField(
            model_name='userdocument',
            name='display_name',
            field=models.CharField(default='', max_length=255, verbose_name='Anzeigename'),
        ),
        migrations.AddField(
            model_name='userdocument',
            name='original_filename',
            field=models.CharField(default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='userdocument',
            name='file',
            field=models.FileField(upload_to='user_documents/%Y/%m/%d/'),
        ),
        migrations.AlterField(
            model_name='userdocument',
            name='notes',
            field=models.TextField(blank=True, default='', verbose_name='Notizen'),
        ),
    ]
