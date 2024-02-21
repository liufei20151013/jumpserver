import os

import django


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

from unittest import TestCase
from django.utils import timezone
import datetime
from assets.models import Node
from perms.const import ActionChoices
from common.utils import get_object_or_none
from perms.serializers import ActionChoicesField
from itsm.task import sync_itsm_data, sync_itsm_data_periodic
from itsm.main import process_data, save_or_update_asset_permission, save_or_update_asset, to_internal_value, \
    extend_permission


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
        permissions = [
            {
                "username": "liufei",
                "date_expired": "2024-05-01"
            }
        ]
        extend_permission(permissions)

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
        #         "permission_name": "12-permission",
        #         "username": "liufei",
        #         "asset_name": "11",
        #         "account": ["@SPEC", "root"],
        #         "protocol": ["ssh/22"],
        #         "action": ["connect", "upload", "download", "copy", "paste", "delete", "share"],
        #         "date_start": "2023-02-23T10:53:23.879Z",
        #         "date_expired": "2093-01-30T10:53:23.879Z"
        #     }
        # ]
        # save_or_update_asset_permission(permissions)

        # 创建或更新账号
        # accounts = [
        #     {
        #         "account_name": "10.1.12.127-root",
        #         "account_username": "root",
        #         "secret_type": "password",
        #         "secret": "",
        #         "su_from": "",
        #         "asset_name": "10.1.12.126",
        #         "is_privileged": "True"
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
        # assets = [
            # {
        #         "asset_type": "host",
        #         "asset_name": "10.1.12.12",
        #         "address": "10.1.12.12",
        #         "platform": "Linux",
        #         "assetnode_name": "/Default/开发2/java2",
        #         "protocol": ["ssh/22", "sftp/2222"],
        #         "default_db": ""
        #     }
        #     , {
        #         "asset_type": "host",
        #         "asset_name": "10.1.12.11",
        #         "address": "10.1.12.11",
        #         "platform": "Linux",
        #         "assetnode_name": "/Default/开发2/java2",
        #         "protocol": ["ssh/2266"],
        #         "default_db": ""
        #     }, {
        #         "asset_type": "db",
        #         "asset_name": "10.1.12.224",
        #         "address": "10.1.12.224",
        #         "platform": "MySQL",
        #         "assetnode_name": "/Default/开发/mysql2",
        #         "protocol": ["mysql/3309"],
        #         "default_db": "fit2cloud"
        #     }, {
        #         "asset_type": "web",
        #         "asset_name": "salesview 平台",
        #         "address": "http://10.1.12.168",
        #         "platform": "Website",
        #         "assetnode_name": "/Default/开发/web2",
        #         "protocol": ["http/80"],
        #         "default_db": ""
        #     }

        #     {
        #         "asset_type": "db",
        #         "asset_name": "salesview 平台26",
        #         "address": "10.1.12.173",
        #         "platform": "Kingbase",
        #         "assetnode_name": "/Default/开发/数据库",
        #         "protocol": ["Kingbase/54321"],
        #         "default_db": "",
        #         "permission_name": "173-permission",
        #         "username": "liufei",
        #         "account": ["@SPEC", "root"],
        #         "action": ["connect", "upload", "download", "copy", "paste", "delete", "share"],
        #         # "date_start": "2023-02-23T10:53:23.879Z",
        #         # "date_expired": "2093-01-30T10:53:23.879Z",
        #         "account_name": "10.1.12.173-root",
        #         "account_username": "root",
        #         "secret_type": "password",
        #         "secret": "",
        #         "su_from": "",
        #         "is_privileged": "True",
        #         "default_db": "js_db"
        #     }
        # ]
        # save_or_update_asset(assets)

    def test_sync_itsm_data(self):
        # process_data()
        # sync_itsm_data()
        # sync_itsm_data_periodic()
        # sync_itsm_data.delay()
        try:
            print((timezone.now() + timezone.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"))
            years = 70
            print((timezone.now() + timezone.timedelta(days=365 * years, hours=8)).strftime("%Y-%m-%d %H:%M:%S"))
            # print(date_expired_default().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            print(e)
