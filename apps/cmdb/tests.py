import os
import time

import django


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

import uuid
from assets.models import Asset, Node, Database
from orgs.models import Organization
from orgs.utils import set_current_org
from datetime import datetime, timedelta
from collections import defaultdict
from cmdb.main import save_host_asset, save_db_asset, save_middleware_asset
from dlt.tasks import process_data

from unittest import TestCase


class TestTaskCase(TestCase):
    def test(self):
        # current_time = datetime.now()
        #
        # # 2. 计算往前推指定分钟的时间（timedelta 用于时间差计算）
        # before_time = current_time - timedelta(minutes=10)
        #
        # # 3. 格式化为指定字符串格式
        # formatted_time = before_time.strftime("%Y-%m-%d %H:%M:%S")
        # print(formatted_time)
        asset_org_dict = {}
        middleware_data = [
            {
                'sys_number': 'TK-001',
                'sys_name': '运维系统',
                'bk_inst_name': '测试01',
                'control_addr': 'https://www.baidu.com',
                'bk_host_innerip': '10.1.10.11',
                'bk_os_type': '1',
                'app_department': '应用部门',
                'listen_port': '443',
                "create_time": "2026-04-16T10:28:41.178+08:00",
                "last_time": "2026-04-16T10:30:41.178+08:00"
            },{
                'sys_number': 'TK-001',
                'sys_name': '运维系统',
                'bk_inst_name': '测试02',
                'control_addr': 'http://10.1.12.240',
                'bk_host_innerip': '10.1.10.11',
                'bk_os_type': '1',
                'app_department': '应用部门',
                'listen_port': '80',
                "create_time": "2026-04-16T10:28:41.178+08:00",
                "last_time": "2026-04-16T10:30:41.178+08:00"
            }
        ]

        save_middleware_asset(middleware_data, asset_org_dict, True)


    def test2(self):
        start_time = time.time()
        # print("获取堡垒机上原始资产数据 Start.")
        # old_asset_org_dict = {}
        # orgs = Organization.objects.exclude(id=Organization.SYSTEM_ID)
        # for org in orgs:
        #     set_current_org(org)
        #
        #     # jms_开头的是堡垒机服务器
        #     assets = Asset.objects.exclude(name__istartswith='jms_')
        #     for asset in assets:
        #         key = f"{str(org.id)}_{asset.name}"
        #         old_asset_org_dict.update({key: asset.id})
        # print("获取堡垒机上原始资产数据 End.")

        asset_org_dict = {}
        # host_data = [
        #     {
        #         'sys_number': '',
        #         'sys_name': '',
        #         'bk_host_name': 'aaatpsql001',
        #         'bk_host_innerip': '10.28.211.211',
        #         'bk_os_type': '1',
        #         'app_department': '应用部门',
        #         'bk_os_name': '7',
        #         'UseOffice': '系统管理室',
        #         "create_time": "2026-04-16T10:28:41.178+08:00",
        #         "last_time": "2026-05-13T17:46:41.178+08:00"
        #     },{
        #         'sys_number': 'TK-001',
        #         'sys_name': '运维系统',
        #         'bk_host_name': 'aaa主机02',
        #         'bk_host_innerip': '10.1.10.12',
        #         'bk_os_type': '2',
        #         'app_department': '应用部门',
        #         'bk_os_name': '2019'
        #     },{
        #         'sys_number': 'TK-001',
        #         'sys_name': '运维系统',
        #         'bk_host_name': 'aaa主机03',
        #         'bk_host_innerip': '10.1.10.13',
        #         'bk_os_type': '2',
        #         'app_department': '应用部门',
        #         'bk_os_name': '2016'
        #     },{
        #         'sys_number': 'TK-001',
        #         'sys_name': 'aaa运维系统',
        #         'bk_host_name': '主机04',
        #         'bk_host_innerip': '10.1.10.14',
        #         'bk_os_type': '3',
        #         'app_department': '应用部门',
        #         'bk_os_name': '6.7'
        #     }
        # ]
        org_data_map = defaultdict(lambda: {
            "create": [],
            "update": [],
            "host": [],
            "db": [],
            "device": [],
            "web": [],
            "node": [],
            "protocol": []
        })

        user_org_dict = {}
        host_data = []
        i = 0
        while i < 10000:
            data = {
                'sys_number': 'sys_00' + str(i // 100),
                'sys_name': '系统_001',
                'bk_host_name': '测试_' + str(i+1),
                'bk_host_innerip': '10.28.211.211',
                'bk_os_type': '1',
                'app_department': '应用部门',
                'bk_os_name': '7',
                'UseOffice': '系统管理室',
                "create_time": "2026-04-16T10:28:41.178+08:00",
                "last_time": "2026-05-13T17:46:41.178+08:00"
            }
            host_data.append(data)
            i += 1
        save_host_asset(host_data, user_org_dict, False, org_data_map)
        end_time = time.time()
        total_seconds = end_time - start_time

        print(f"程序总执行时间：{total_seconds:.2f} 秒")

        # bk_obj_id = 'db_redis'
        # db_data = [
        #     {
        #         'sys_number': 'TK-002',
        #         'sys_name': '数据库',
        #         'bk_inst_name': '数据库01',
        #         'ip_addr': '10.1.10.11',
        #         'port': '6379',
        #         'app_department': '应用部门',
        #         'db_inst_name': 'db01',
        #         'db_version': '5'
        #     }, {
        #         'sys_number': 'TK-002',
        #         'sys_name': '数据库',
        #         'bk_inst_name': '数据库02',
        #         'ip_addr': '10.1.10.12',
        #         'port': '6379',
        #         'app_department': '应用部门',
        #         'db_inst_name': 'db02',
        #         'db_version': '6.88'
        #     }
        # ]
        #
        # save_db_asset(db_data, asset_org_dict, bk_obj_id)
        #
        # bk_obj_id = 'db_cluster'
        # db_data = [
        #     {
        #         'sys_number': 'TK-002',
        #         'sys_name': '数据库',
        #         'bk_inst_name': '集群01',
        #         'ip_addr': '10.1.10.13,10.1.10.14,10.1.10.15',
        #         'port': '6379',
        #         'app_department': '应用部门',
        #         'db_inst_name': 'db01',
        #         'db_tpye': 'Redis',
        #         'db_version': '5'
        #     }
        # ]
        #
        # save_db_asset(db_data, asset_org_dict, bk_obj_id)
        #
        # if len(asset_org_dict) > 0:
        #     print("删除已下线的资产 Start.")
        #     offline_asset_org_dict = {k: v for k, v in old_asset_org_dict.items() if k not in asset_org_dict}
        #     for key, value in offline_asset_org_dict.items():
        #         items = key.split("_")
        #         org = Organization.objects.get(id=uuid.UUID(items[0]))
        #         set_current_org(org)
        #
        #         Asset.objects.get(id=value).delete()
        #         print("Success to delete asset: {}, org_id: {}.".format(items[1], items[0]))
        #     print("删除已下线的资产 End.")


    def test3(self):
        asset_org_dict = {}
        # bk_obj_id = 'db_redis'
        # db_data = [
        #     {
        #         'sys_number': 'TK-002',
        #         'sys_name': '数据库',
        #         'bk_inst_name': '数据库01',
        #         'ip_addr': '10.1.10.11',
        #         'port': '6379',
        #         'app_department': '应用部门',
        #         'db_inst_name': 'db01',
        #         'db_version': '5'
        #     },{
        #         'sys_number': 'TK-002',
        #         'sys_name': '数据库',
        #         'bk_inst_name': '数据库02',
        #         'ip_addr': '10.1.10.12',
        #         'port': '6379',
        #         'app_department': '应用部门',
        #         'db_inst_name': 'db02',
        #         'db_version': '6.88'
        #     }
        # ]
        #
        # save_db_asset(db_data, asset_org_dict, bk_obj_id)

        bk_obj_id = 'db_cluster'
        db_data = [
            {
                'sys_number': 'TK-002',
                'sys_name': '数据库',
                'bk_inst_name': '集群01',
                'ip_addr': '10.1.10.13,10.1.10.14,10.1.10.15',
                'port': '6379',
                'app_department': '应用部门',
                'db_inst_name': 'db01',
                'db_tpye': 'Redis',
                'db_version': '5'
            },{
                'sys_number': 'TK-003',
                'sys_name': '特殊数据库',
                'bk_inst_name': '集群02',
                'ip_addr': '10.1.10.13,10.1.10.14,10.1.10.15',
                'port': '1678',
                'app_department': '应用部门',
                'db_inst_name': 'db02',
                'db_tpye': 'ESSBASE',
                'db_version': '5'
            }
        ]

        save_db_asset(db_data, asset_org_dict, bk_obj_id)


    def test4(self):
        # process_data(True)

        # orgs = []
        # org_name = '运维开发部'
        # org_names = ['系统运行与信息安全管理部-系统管理室', org_name]
        # for name in org_names:
        #     org, created = Organization.objects.get_or_create(name=name)
        #     orgs.append(org)
        #     if created:
        #         print("Success to create org[{}].".format(name))

        # node_path = '/DEFAULT/TK-001-运维系统11'
        # asset = Asset.objects.filter(name='测试02').first()
        # node = Node.objects.filter(full_value=node_path).first()
        # if node:
        #     exist = asset.nodes.filter(id=node.id).exists()
        #     if not exist:
        #         asset.nodes.set([node.id])
        # else:
        #     node = Node.create_node_by_full_value(node_path)
        #     asset.nodes.set([node.id])

        default_db = 'test'
        asset = Asset.objects.filter(name='数据库01').first()
        asset_model = Database.objects.filter(asset_ptr_id=asset.id).first()
        if asset_model:
            asset_model.db_name = default_db
        else:
            asset_model = Database(asset_ptr_id=asset.id, db_name=default_db)
        asset_model.__dict__.update(asset.__dict__)
        asset_model.save()
