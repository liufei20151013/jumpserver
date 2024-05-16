# Generated by Django 3.2.12 on 2022-07-11 08:59

import time

from django.conf import settings
from django.db import migrations, models


def migrate_asset_protocols(apps, schema_editor):
    asset_model = apps.get_model('assets', 'Asset')
    protocol_model = apps.get_model('assets', 'Protocol')

    count = 0
    bulk_size = 50000
    print("\n\tStart migrate asset protocols")
    while True:
        start = time.time()
        assets = asset_model.objects.all()[count:count + bulk_size]
        if not assets:
            break
        count += len(assets)
        assets_protocols = []

        for asset in assets:
            old_protocols = asset._protocols or '{}/{}'.format(asset.protocol, asset.port) or 'ssh/22'

            if ',' in old_protocols:
                _protocols = old_protocols.split(',')
            else:
                _protocols = old_protocols.split()

            for name_port in _protocols:
                name_port_list = name_port.split('/')
                if len(name_port_list) != 2:
                    continue

                name, port = name_port_list
                protocol = protocol_model(**{'name': name, 'port': port, 'asset': asset})
                assets_protocols.append(protocol)

        protocol_model.objects.bulk_create(assets_protocols, ignore_conflicts=True)
        print("\t - Create asset protocols: {}-{} using: {:.2f}s".format(
            count - len(assets), count, time.time() - start
        ))


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('assets', '0098_auto_20220430_2126'),
    ]

    operations = [
        migrations.RenameField(
            model_name='asset',
            old_name='protocols',
            new_name='_protocols',
        ),
        migrations.CreateModel(
            name='Protocol',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=32, verbose_name='Name')),
                ('port', models.IntegerField(verbose_name='Port')),
                ('asset',
                 models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='protocols', to='assets.asset',
                                   verbose_name='Asset')),
            ],
        ),
        migrations.RunPython(migrate_asset_protocols),
    ]
