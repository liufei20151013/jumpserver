# Generated by Django 4.1.13 on 2024-03-07 02:08

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('assets', '0127_automation_remove_account'),
    ]

    operations = [
        migrations.CreateModel(
            name='FavoriteNode',
            fields=[
                ('created_by', models.CharField(blank=True, max_length=128, null=True, verbose_name='Created by')),
                ('updated_by', models.CharField(blank=True, max_length=128, null=True, verbose_name='Updated by')),
                ('date_created', models.DateTimeField(auto_now_add=True, null=True, verbose_name='Date created')),
                ('date_updated', models.DateTimeField(auto_now=True, verbose_name='Date updated')),
                ('comment', models.TextField(blank=True, default='', verbose_name='Comment')),
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('org_id', models.CharField(blank=True, db_index=True, default='', max_length=36, verbose_name='Organization')),
                ('name', models.CharField(max_length=128, verbose_name='Name')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'FavoriteNode',
                'ordering': ('name',),
                'unique_together': {('org_id', 'name', 'user')},
            },
        ),
        migrations.AddField(
            model_name='favoriteasset',
            name='favoriteNode',
            field=models.ForeignKey(default='', on_delete=django.db.models.deletion.CASCADE, to='assets.favoritenode'),
        ),
    ]
