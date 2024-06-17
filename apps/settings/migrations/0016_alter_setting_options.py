# Generated by Django 4.1.13 on 2024-06-13 06:33

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('settings', '0015_alter_setting_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='setting',
            options={'permissions': [('change_email', 'Can change email setting'), ('change_auth', 'Can change auth setting'), ('change_ops', 'Can change auth ops'), ('change_ticket', 'Can change auth ticket'), ('change_virtualapp', 'Can change virtual app setting'), ('change_announcement', 'Can change auth announcement'), ('change_vault', 'Can change vault setting'), ('change_chatai', 'Can change chat ai setting'), ('change_systemmsgsubscription', 'Can change system msg sub setting'), ('change_sms', 'Can change sms setting'), ('change_security', 'Can change security setting'), ('change_clean', 'Can change clean setting'), ('change_interface', 'Can change interface setting'), ('change_license', 'Can change license setting'), ('change_terminal', 'Can change terminal setting'), ('change_other', 'Can change other setting'), ('change_itsm', 'Can change itsm setting'), ('change_itsm_sync_js', 'Can change itsm sync JumpServer setting'), ('change_itsm_sync_js_mfa', 'Can change itsm sync JumpServer mfa setting')], 'verbose_name': 'System setting'},
        ),
    ]
