# Generated by Django 4.1.13 on 2024-08-28 06:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orgs', '0015_auto_20221220_1956'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='org_code',
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name='Organization Code'),
        ),
    ]
