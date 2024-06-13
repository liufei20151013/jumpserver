import json
import os

import django


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

from itsm.sync_from_js import process_js_data
from accounts.models import ChangeSecretAutomation, AccountBackupAutomation, AccountTemplate, Account, \
    AutomationExecution
from accounts.const import SecretStrategy, SSHKeyStrategy
from orgs.models import Organization
from unittest import TestCase
from django.utils import timezone
from datetime import datetime
from assets.models import Node, Asset
from perms.const import ActionChoices
from common.utils import get_object_or_none
from perms.serializers import ActionChoicesField
from itsm.task import sync_itsm_data, sync_itsm_data_periodic
from itsm.main import process_data, save_or_update_asset_permission, save_or_update_asset, to_internal_value, \
    extend_permission, save_or_update_asset_account


class TestTaskCase(TestCase):
    def test_update_user_state(self):
        # 禁用用户
        # users = [{
        #     'username': 'aaa'
        # }, {
        #     'username': 'app'
        # }]
        # update_user_state(users)

        # 移除用户授权
        # permissions = [{
        #     'username': 'liufei',
        #     'asset_name': '10.1.12.126'
        # }]
        # remove_user_asset_permission(permissions)

        # 转换 actions
        # self._choice_cls = ActionChoices
        # actions = ["connect", "upload", "download", "copy", "paste", "delete", "share"]
        # print(ActionChoicesField.to_internal_value(self, actions))
        # print(to_internal_value(actions))

        # 延期授权
        # permissions = [
        #     {
        #         "username": "liufei",
        #         "date_expired": "2024-07-01"
        #     }
        # ]
        # extend_permission(permissions)

        # 创建或更新授权
        # permissions = [
        # {
        #     "permission_name": "10.1.12.127-permission",
        #     "username": "liufei",
        #     "asset_name": "10.1.12.127",
        #     "account": ["@SPEC", "root"],
        #     "protocol": ["ssh/22", "sftp/22"],
        #     "action": ["connect", "upload", "download", "copy", "paste", "delete", "share"],
        #     "date_start": "2023-02-23T10:53:23.879Z",
        #     "date_expired": "2093-01-30T10:53:23.879Z"
        # },
        # {
        #     "permission_name": "10.1.12.126-permission",
        #     "username": "liufei2",
        #     "asset_name": "10.1.12.126",
        #     "account": ["@SPEC", "root"],
        #     "protocol": ["ssh/22", "sftp/22"],
        #     "action": ["connect", "upload", "download", "copy", "paste", "delete", "share"],
        #     "date_start": "2023-02-23T10:53:23.879Z",
        #     "date_expired": "2093-01-30T10:53:23.879Z"
        # },
        # {
        #     "permission_name": "10.1.12.126-permission",
        #     "username": "liufei",
        #     "asset_name": "10.1.12.126",
        #     "account": ["@SPEC", "root"],
        #     "protocol": ["ssh/22", "sftp/22"],
        #     "action": ["connect", "upload", "download", "copy", "paste", "delete", "share"],
        #     "date_start": "2023-02-23T10:53:23.879Z",
        #     "date_expired": "2093-01-30T10:53:23.879Z"
        # },
        # {
        #     "permission_name": "11-permission",
        #     "username": "liufei",
        #     "asset_name": "11",
        #     "account": ["@SPEC", "root"],
        #     "action": ["connect", "upload", "download", "copy"],
        #     "date_start": "2023-02-23T10:53:23.879Z",
        #     "date_expired": "2093-01-30T10:53:23.879Z"
        # },
        # {
        #     "permission_name": "12-permission",
        #     "username": "liufei",
        #     "asset_name": "11",
        #     "account": ["@SPEC", "root"],
        #     "protocol": ["ssh/22"],
        #     "action": ["connect", "upload", "download", "copy"]
        # },
        #     {
        #         "permission_name": "12-permission_root",
        #         "username": "liufei",
        #         "asset_name": "10.1.12.12",
        #         "account": ["@SPEC", "root"],
        #         "protocol": ["ssh/22"],
        #         "action": ["connect", "upload", "download", "copy", "paste", "delete", "share"],
        #         "date_expired": "2024-05-01"
        #     }
        # ]
        # save_or_update_asset_permission(permissions)

        # 创建或更新账号
        # accounts = [
        #     {
        #         "asset_name": "10.1.12.126",
        #         "account_username": "root2"
        #         # ,
        #         # "account_name": "10.1.12.127-root",
        #         # "secret_type": "password",
        #         # "secret": "",
        #         # "su_from": "",
        #         # "is_privileged": "True"
        #     }
        # ]
        # save_or_update_asset_account(accounts)

        # 创建资产节点
        # assetnode_name = '/Default/开发1/java1'
        # root_node = Node.objects.filter(value='Default').first()
        # for index, value in enumerate(assetnode_name.split("/")):
        #     if index > 0:
        #         node = get_object_or_none(Node, value=value)
        #         if not node:
        #             if index == 1:
        #                 print("Root node[{}] is not exist!".format(value))
        #             else:
        #                 root_node.get_or_create_child(value=value)
        #                 root_node = Node.objects.filter(value=value).first()
        # print(root_node.value)

        # 创建资产
        assets = [
            {
                "asset_type": "host",
                "asset_name": "salesview 平台243",
                "address": "10.1.12.18",
                "platform": "Linux",
                "assetnode_name": "/Default/开发/test",
                "protocol": "ssh/22",
                "default_db": "",
                "permission_name": "18-permissionwww",
                "username": "admin",
                "action": ["connect", "upload", "download", "copy", "paste", "delete", "share"],
                "account_username": "appusr",
                "secret_type": "password",
                "secret": "",
                "su_from": "",
            }
        ]
        save_or_update_asset(assets, 0)

        # node_name = '/Default/开发/test'
        # index = node_name.find('/', 1)
        # print(index)
        # print(node_name[1:index])

    def test_sync_itsm_data(self):
        process_js_data()

        # area = 'swd,wdwd,wdwd'
        # areaStr = str(str(area).split(','))
        # print(areaStr)

        # process_data()
        # sync_itsm_data()
        # sync_itsm_data_periodic()
        # sync_itsm_data.delay()

        # try:
        #     print((timezone.now() + timezone.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"))
        #     years = 70
        #     print((timezone.now() + timezone.timedelta(days=365 * years, hours=8)).strftime("%Y-%m-%d %H:%M:%S"))
        #     # print(date_expired_default().strftime("%Y-%m-%d %H:%M:%S"))
        # except Exception as e:
        #     print(e)

        # account_username = 'administrator'
        # asset = get_object_or_none(Asset, name='10.1.12.121')
        # accountTemplates = AccountTemplate.objects.filter(username=account_username)
        #
        # accountTemplate = accountTemplates.first()
        # account = Account.objects.create(asset=asset,
        #                                  name=account_username,
        #                                  username=account_username,
        #                                  privileged=accountTemplate.privileged,
        #                                  secret_type=accountTemplate.secret_type,
        #                                  _secret=accountTemplate.secret,
        #                                  org_id=Organization.DEFAULT_ID)
        #
        # # 主机创建新账号后立即改密
        # try:
        #     name = 'tentative_' + asset.name
        #     password_rules = '{length: 30, lowercase: true, uppercase: true, digit: true, symbol: true}'
        #     automation = ChangeSecretAutomation.objects.create(name=name,
        #                                                        accounts=[account_username],
        #                                                        is_active=True,
        #                                                        is_periodic=False,
        #                                                        password_rules=password_rules,
        #                                                        secret='',
        #                                                        secret_strategy=SecretStrategy.random,
        #                                                        secret_type='password',
        #                                                        ssh_key_change_strategy=SSHKeyStrategy.add)
        #     automation.assets.set([asset])
        #     automation.save()
        #
        #     task = AutomationExecution.objects.create(automation=automation)
        #     print(task.id)
        # except Exception as e:
        #     print(e)
        #     account.delete()
