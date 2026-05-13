import re
import uuid
from urllib.parse import urlparse

import requests
import json

from docutils.nodes import comment

from orgs.utils import set_current_org

from orgs.models import Organization
from assets.models import Asset, Platform, Database, Node, Host, Protocol, Device, Web, PlatformProtocol
from common.utils import get_logger, get_object_or_none

from django.conf import settings
from datetime import datetime
import croniter

logger = get_logger(__name__)


def process_data(isFullSync):
    enabled = settings.CMDB_ENABLED
    if not enabled:
        print('当前 CMDB 同步功能未开启, 不需要处理')
        return

    old_asset_org_dict = {}
    if isFullSync:
        print("获取堡垒机上原始资产数据 Start.")
        orgs = Organization.objects.exclude(id=Organization.SYSTEM_ID)
        for org in orgs:
            set_current_org(org)

            # jms_开头的是堡垒机服务器
            assets = Asset.objects.exclude(name__istartswith='jms_')
            for asset in assets:
                key = f"{str(org.id)}_{asset.name}"
                old_asset_org_dict.update({key: asset.id})
        print("获取堡垒机上原始资产数据 End.")

    asset_org_dict = {}
    user_org_dict = {}

    print("查询所有主机资产 Start.")
    result = search_host_asset()
    if result['code'] != 0:
        print("查询 CMDB 主机数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
        return

    host_data = result['data']['list']
    print("查询 CMDB 主机数据成功，total: {} 条".format(len(host_data)))

    save_host_asset(host_data, asset_org_dict, user_org_dict, isFullSync)
    print("查询所有主机资产 End.")

    print("查询PC机 Start.")
    objects = {
        "pc_server": "PC机"
    }
    for bk_obj_id, bk_obj_name in objects.items():
        print("查询 bk_obj_id: {}, bk_obj_name: {}".format(bk_obj_id, bk_obj_name))
        result = search_other_asset_no_region(bk_obj_id)
        if result['code'] != 0:
            print("查询 CMDB PC机数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
            return

        pc_host_data = result['data']['list']
        print("查询 bk_obj_id: {}, bk_obj_name: {}，total: {} 条".format(bk_obj_id, bk_obj_name, len(pc_host_data)))

        save_pc_host_asset(pc_host_data, asset_org_dict, isFullSync, bk_obj_id)
    print("查询所有PC机 End.")

    print("查询中间件 Start.")
    objects = {
        "mid_bes": "Bes",
        "mid_mq": "MQ",
        "weblogic_inst": "WebLogic应用实例"
    }

    # 2 开发测试  6 待更新
    regions = ["1", "3", "4", "5", "7"]
    for bk_obj_id, bk_obj_name in objects.items():
        for region in regions:
            print("查询 bk_obj_id: {}, bk_obj_name: {}, region: {}".format(bk_obj_id, bk_obj_name, region))
            result = search_other_asset(bk_obj_id, region)
            if result['code'] != 0:
                print("查询 CMDB 中间件数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
                return

            middleware_data = result['data']['list']
            print("查询 bk_obj_id: {}, bk_obj_name: {}, region: {}, total: {} 条"
                  .format(bk_obj_id, bk_obj_name, region, len(middleware_data)))

            save_middleware_asset(middleware_data, asset_org_dict, isFullSync, bk_obj_id)
    print("查询所有中间件 End.")

    print("查询网络设备 Start.")
    objects = {
        "network_device": "网络设备"
    }
    for bk_obj_id, bk_obj_name in objects.items():
        print("查询 bk_obj_id: {}, bk_obj_name: {}".format(bk_obj_id, bk_obj_name))
        result = search_other_asset_no_region(bk_obj_id)
        if result['code'] != 0:
            print("查询 CMDB 网络设备数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
            return

        network_device_data = result['data']['list']
        print("查询 bk_obj_id: {}, bk_obj_name: {}，total: {} 条".format(bk_obj_id, bk_obj_name, len(network_device_data)))

        save_network_device_asset(network_device_data, asset_org_dict, isFullSync)
    print("查询所有网络设备 End.")

    print("查询存储设备 Start.")
    objects = {
        "storage_oss": "对象存储",
        "fc_storage": "SAN存储",
        "network_storage": "NAS存储"
    }
    # 3 开发测试  1 待更新
    storage_regions = ["2", "4", "5", "6"]
    for bk_obj_id, bk_obj_name in objects.items():
        for storage_region in storage_regions:
            print("查询 bk_obj_id: {}, bk_obj_name: {}, region: {}".format(bk_obj_id, bk_obj_name, storage_region))
            result = search_other_asset(bk_obj_id, storage_region)
            if result['code'] != 0:
                print("查询 CMDB 存储设备数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
                return

            storage_device_data = result['data']['list']
            print("查询 bk_obj_id: {}, bk_obj_name: {}, region: {}, total: {} 条"
                  .format(bk_obj_id, bk_obj_name, storage_region, len(storage_device_data)))

            save_storage_device_asset(storage_device_data, asset_org_dict, isFullSync)
    print("查询所有存储设备 End.")

    print("查询所有数据库资产 Start.")
    objects = {
        "db_redis": "Redis",
        "db_sqlserver": "SQLserver",
        "db_postgresql": "PostgreSQL",
        "db_mysql": "MySQL",
        "db_mongodb": "MongoDB",
        "db_oracle": "ORACLE",
        "db_tdsql_mysql": "TDSQL-MYSQL",
        "db_tdsql_pg": "TDSQL-PG",
        # "db_dm": "DM",
        # "db_elasticsearch": "TBDS",
        # "db_essbase": "ESSBASE",
        # "db_sybaseiq": "SybaseIQ",
        # "db_hana": "HANA",
        # "db_oceanbase": "OceanBase",
        # "db_tidb": "TiDB",
        # "db_gaussdb": "GaussDB"
    }
    for bk_obj_id, bk_obj_name in objects.items():
        for region in regions:
            print("查询 bk_obj_id: {}, bk_obj_name: {}, region: {}".format(bk_obj_id, bk_obj_name, region))
            result = search_other_asset(bk_obj_id, region)
            if result['code'] != 0:
                print(
                    "查询 CMDB 数据库资产数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
                return

            db_data = result['data']['list']
            print("查询 bk_obj_id: {}, bk_obj_name: {}, region: {}, total: {}条".format(bk_obj_id, bk_obj_name, region, len(db_data)))

            save_db_asset(db_data, asset_org_dict, bk_obj_id, isFullSync)
    print("查询所有数据库资产、网络设备 End.")


    if isFullSync and len(asset_org_dict) > 0:
        print("删除已下线的资产 Start.")
        offline_asset_org_dict = {k: v for k, v in old_asset_org_dict.items() if k not in asset_org_dict}
        for key, value in offline_asset_org_dict.items():
            items = key.split("_")
            org = Organization.objects.get(id=uuid.UUID(items[0]))
            set_current_org(org)

            Asset.objects.get(id=value).delete()
            print("Success to delete asset: {}, org_id: {}.".format(items[1], items[0]))
        print("删除已下线的资产 End.")

    print('CMDB 数据处理 End.')


# 专业公司的数据库资产不在CMDB管理，所有数据库资产归属 系统运行与信息安全管理部-系统管理室 管理
# 所有的数据库资产都同步到太平金科的 系统运行与信息安全管理部-系统管理室 组织下
def save_db_asset(assets, asset_org_dict, bk_obj_id, isFullSync):
    network_dept = '系统运行与信息安全管理部-系统管理室'
    orgs = Organization.objects.filter(name=network_dept)
    if not orgs.exists():
        print("It does not exist organization [{}].".format(network_dept))
        return
    org = orgs.first()
    set_current_org(org)

    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync:
            if not compare_time(update_time):
                continue

        sys_number = asset.get('sys_number', '')
        sys_name = asset.get('sys_name', '')
        asset_name = asset.get('bk_inst_name', 'ip_addr')
        ip_addr = asset.get('ip_addr', '')
        db_port = asset.get('port', '')
        org_name = asset.get('app_department', '')
        # 未维护信息过滤掉
        if not ip_addr or not db_port or not org_name:
            print("There exist null parameter situations, skip.")
            continue

        # 在 Default 组织下管理所有资产，在归属部门 app_department 对应组织下管理关联资产
        # DEFAULT_ORG = Organization.objects.get(id=Organization.DEFAULT_ID)
        # orgs = [DEFAULT_ORG]
        # org = Organization.objects.filter(name=org_name).first()
        # if org:
        #     orgs.append(org)
        # else:
        #     print("堡垒机上不存在组织[{}]，asset_name: {}.".format(org_name, asset_name))
        #     org = Organization.objects.create(name=org_name)
        #     orgs.append(org)
        #     print("Success to create org[{}].".format(org_name))


        try:
            print("Save or update db asset[{}].".format(asset_name))
            default_db = ''
            db_port = str(db_port)
            if bk_obj_id == 'db_redis':
                protocol = "redis/" + db_port
                db_version = asset.get('db_version', '0')
                if db_version and str_to_int(db_version) >= 6:
                    platform = Platform.objects.filter(name='Redis6+').first()
                else:
                    platform = Platform.objects.filter(name='Redis').first()
            elif bk_obj_id == 'db_sqlserver':
                protocol = "sqlserver/" + db_port
                platform = Platform.objects.filter(name='SQLServer').first()
                # 缺少默认数据库  非必填
            elif bk_obj_id == 'db_postgresql' or bk_obj_id == 'db_tdsql_pg':
                protocol = "postgresql/" + db_port
                platform = Platform.objects.filter(name='PostgreSQL').first()
                # 缺少默认数据库
                default_db = 'postgres'
            elif bk_obj_id == 'db_mysql' or bk_obj_id == 'db_tdsql_mysql':
                protocol = "mysql/" + db_port
                platform = Platform.objects.filter(name='MySQL').first()
                # 缺少默认数据库  非必填
            elif bk_obj_id == 'db_mongodb':
                protocol = "mongodb/" + db_port
                platform = Platform.objects.filter(name='MongoDB').first()
                # 缺少默认数据库
                default_db = 'admin'
            elif bk_obj_id == 'db_oracle':
                protocol = "oracle/" + db_port
                default_db = asset.get('db_inst_name', '')
                if default_db and len(default_db) == 0:
                    default_db = asset.get('sid', '')
                    if default_db and len(default_db) == 0:
                        continue
                platform = Platform.objects.filter(name='Oracle').first()
                # 缺少默认数据库  非必填
            elif bk_obj_id == 'db_dm':
                protocol = "dameng/" + db_port
                platform = Platform.objects.filter(name='Dameng').first()
                # 缺少默认数据库  非必填
            elif (bk_obj_id == 'db_elasticsearch' or bk_obj_id == 'db_essbase' or bk_obj_id == 'db_sybaseiq' or
                  bk_obj_id == 'db_hana' or bk_obj_id == 'db_oceanbase' or bk_obj_id == 'db_tidb' or
                  bk_obj_id == 'db_gaussdb' or bk_obj_id == 'db_custom'):
                # 自定义类型 远程应用方式连接
                protocol = "orig_app/" + db_port
                platform = Platform.objects.filter(name='OriginalApp').first()
            else:
                print("bk_obj_id[{}] is not exist, skip.".format(bk_obj_id))
                continue


            if not platform:
                print("asset[{}]'s platform is not exist, bk_obj_id: {}.".format(asset_name, bk_obj_id))
                continue

            asset_protocol = []
            asset_protocol.append(protocol)

            for org in orgs:
                set_current_org(org)

                full_assetnode_name = "/" + org.name
                if sys_number and sys_name:
                    assetnode_name = sys_number + '-' + sys_name
                    full_assetnode_name = full_assetnode_name + "/" + assetnode_name

                # 用户确认全平台主机名唯一
                assetList = Asset.objects.filter(name=asset_name)
                if not assetList.exists():
                    a = Asset.objects.create(name=asset_name,
                                             address=ip_addr,
                                             platform=platform,
                                             org_id=org.id)

                    if len(default_db) == 0:
                        asset_model = Database(asset_ptr_id=a.id)
                    else:
                        asset_model = Database(asset_ptr_id=a.id, db_name=default_db)
                    asset_model.__dict__.update(a.__dict__)
                    asset_model.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to create db asset[{}].".format(asset_name))
                    continue
                else:
                    for a in assetList:
                        # 更新资产信息
                        # 如果平台不同，先删再加
                        if a.platform_id != platform.id:
                            print(a.type)
                            p = Platform.objects.get(id=a.platform_id)
                            if p.type != platform.type:
                                Asset.objects.get(id=a.id).delete()
                                print("Incompatible platform: old-[{}], new-[{}]; Delete db asset[{}], create it.".format(p.name, platform.name, asset_name))

                                a = Asset.objects.create(name=asset_name,
                                                         address=ip_addr,
                                                         platform=platform,
                                                         org_id=org.id)

                                if len(default_db) == 0:
                                    asset_model = Database(asset_ptr_id=a.id)
                                else:
                                    asset_model = Database(asset_ptr_id=a.id, db_name=default_db)
                                asset_model.__dict__.update(a.__dict__)
                                asset_model.save()
                                print("Success to create db asset[{}].".format(asset_name))
                        else:
                            a.address = ip_addr
                            a.save()

                        key = f"{str(org.id)}_{a.name}"
                        asset_org_dict.update({key: a.id})
                        create_asset_node(full_assetnode_name, a)
                        relate_protocols(asset_protocol, a)
                        print("Success to update asset[{}].".format(asset_name))
                        continue
        except Exception as e:
            print("Failed to save db asset[{}], error:{}".format(asset_name, e))
            raise e

def str_to_int(str_num):
    try:
        # 先转浮点数，再转整数
        return int(float(str_num))
    except (ValueError, TypeError):
        print("输入的字符串无法转换为整数")
        return 0

# 专业公司的网络设备资产不在CMDB管理，所有网络设备资产归属 系统运行与信息安全管理部-网络管理室 管理
# 所有的网络设备都同步到太平金科的系统运行与信息安全管理部-网络管理室组织下
def save_network_device_asset(assets, asset_org_dict, isFullSync):
    network_dept = '系统运行与信息安全管理部-网络管理室'
    orgs = Organization.objects.filter(name=network_dept)
    if not orgs.exists():
        print("It does not exist organization [{}].".format(network_dept))
        return
    org = orgs.first()
    set_current_org(org)

    assetnode_name = '/' + org.name
    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync:
            if not compare_time(update_time):
                continue

        asset_name = asset.get('bk_inst_name', '')
        address = asset.get('ip_address', '')
        manufacturer = asset.get('manufacturer', '')
        # 未维护信息过滤掉
        if not asset_name or not address or not manufacturer:
            print("There exist null parameter situations, skip.")
            continue

        try:
            print("Save or update network device asset[{}].".format(asset_name))
            asset_protocol = ["ssh/22", "telnet/23"]
            if manufacturer == 'h3c':
                platform = Platform.objects.filter(name='H3C').first()
            elif manufacturer == 'huawei':
                platform = Platform.objects.filter(name='Huawei').first()
            elif manufacturer == 'cisco':
                platform = Platform.objects.filter(name='Cisco').first()
            elif manufacturer == 'juniper':
                platform = Platform.objects.filter(name='Juniper').first()
            else:
                platform = Platform.objects.filter(name='Global').first()


            # 用户确认全平台主机名唯一
            assetList = Asset.objects.filter(name=asset_name)
            if not assetList.exists():
                a = Asset.objects.create(name=asset_name,
                                         address=address,
                                         platform=platform,
                                         org_id=org.id)

                asset_model = Device(asset_ptr_id=a.id)
                asset_model.__dict__.update(a.__dict__)
                asset_model.save()

                key = f"{str(org.id)}_{a.name}"
                asset_org_dict.update({key: a.id})
                create_asset_node(assetnode_name, a)
                relate_protocols(asset_protocol, a)
                print("Success to create network device asset[{}].".format(asset_name))
                continue

            for a in assetList:
                # 更新资产信息
                # 如果平台不同，先删再加
                if a.platform_id != platform.id:
                    print(a.type)
                    p = Platform.objects.get(id=a.platform_id)
                    if p.type != platform.type:
                        Asset.objects.get(id=a.id).delete()
                        print("Incompatible platform: old-[{}], new-[{}]; Delete network device asset[{}], create it.".format(p.name,
                                                                                                               platform.name,
                                                                                                               asset_name))

                        a = Asset.objects.create(name=asset_name,
                                                 address=address,
                                                 platform=platform,
                                                 org_id=org.id)

                        asset_model = Device(asset_ptr_id=a.id)
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()
                        print("Success to create network device asset[{}].".format(asset_name))
                else:
                    a.address = address
                    a.save()

                key = f"{str(org.id)}_{a.name}"
                asset_org_dict.update({key: a.id})
                create_asset_node(assetnode_name, a)
                relate_protocols(asset_protocol, a)
                print("Success to update network device asset[{}].".format(asset_name))
        except Exception as e:
            print("Failed to save network device asset[{}], error:{}".format(asset_name, e))
            raise e


def save_middleware_asset(assets, asset_org_dict, isFullSync, bk_obj_id):
    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync:
            if not compare_time(update_time):
                continue

        sys_number = asset.get('sys_number', '')
        sys_name = asset.get('sys_name', '')
        asset_name = asset.get('bk_inst_name', '')
        address = asset.get('control_addr', '')
        listen_port = asset.get('listen_port', '')
        org_name = asset.get('app_department', '')
        if not address or not listen_port or not org_name:
            print("There exist null parameter situations, skip.")
            continue
        if not str(address).__contains__('http'):
            continue

        # 在 Default 组织下管理所有资产，在归属部门 app_department 对应组织下管理关联资产
        # 专业公司的中间件资产不在CMDB管理，所有中间件资产归属 系统运行与信息安全管理部-系统管理室 管理
        org = Organization.objects.get(id=Organization.DEFAULT_ID)
        orgs = [org]
        # if len(org_name) > 0:
        #     org = Organization.objects.filter(name=org_name).first()
        #     if org:
        #         orgs.append(org)
        #     else:
        #         print("堡垒机上不存在组织[{}]，asset_name: {}.".format(org_name, asset_name))
        #         org = Organization.objects.create(name=org_name)
        #         orgs.append(org)
        #         print("Success to create org[{}].".format(org_name))

        try:
            print("Save or update middleware asset[{}].".format(asset_name))
            platform = Platform.objects.filter(name='Website').first()
            asset_protocol = ["http/" + str(listen_port)]

            for org in orgs:
                set_current_org(org)

                full_assetnode_name = "/" + org.name
                if sys_number and sys_name:
                    assetnode_name = sys_number + '-' + sys_name
                    full_assetnode_name = full_assetnode_name + "/" + assetnode_name

                # 用户确认全平台主机名唯一
                assetList = Asset.objects.filter(name=asset_name)
                if not assetList.exists():
                    a = Asset.objects.create(name=asset_name,
                                             address=address,
                                             platform=platform,
                                             org_id=org.id)

                    asset_model = get_web_asset_model(bk_obj_id, '', asset, a)
                    asset_model.__dict__.update(a.__dict__)
                    asset_model.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to create middleware asset[{}].".format(asset_name))
                    continue

                for a in assetList:
                    # 更新资产信息
                    # 如果平台不同，先删再加
                    if a.platform_id != platform.id:
                        p = Platform.objects.get(id=a.platform_id)
                        if p.type != platform.type:
                            Asset.objects.get(id=a.id).delete()
                            print("Incompatible platform: old-[{}], new-[{}]; Delete middleware asset[{}], create it.".format(p.name, platform.name, asset_name))

                            a = Asset.objects.create(name=asset_name,
                                                     address=address,
                                                     platform=platform,
                                                     org_id=org.id)

                            asset_model = get_web_asset_model(bk_obj_id,  '', asset, a)
                            asset_model.__dict__.update(a.__dict__)
                            asset_model.save()
                            print("Success to create middleware asset[{}].".format(asset_name))
                    else:
                        a.address = address
                        a.save()

                        asset_model = update_web_asset_model(bk_obj_id, '', asset, a)
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to update middleware asset[{}].".format(asset_name))
        except Exception as e:
            print("Failed to save middleware asset[{}], error:{}".format(asset_name, e))
            raise e


# 所有存储设备归属系统管理室
def save_storage_device_asset(assets, asset_org_dict, isFullSync, bk_obj_id):
    org = Organization.objects.get(id=Organization.DEFAULT_ID)
    set_current_org(org)

    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync:
            if not compare_time(update_time):
                continue

        asset_name = asset.get('bk_inst_name', '')
        sys_name = asset.get('sys_name', '')
        storage_cls = asset.get('storage_cls', '')
        manufacturer = asset.get('manufacturer', '')   # 厂商
        status = asset.get('status', '') # 配置项状态
        # 未维护信息过滤掉
        if not asset_name or not manufacturer or not storage_cls or not status:
            print("There exist null parameter situations, skip.")
            continue
        if not str(storage_cls).__contains__('http'):
            print("The storage cls does not include http(s), skip.")
            continue
        if not status == '运行':
            continue

        full_assetnode_name = "/" + org.name
        if sys_name:
            full_assetnode_name = full_assetnode_name + "/" + sys_name

        try:
            print("Save or update storage device asset[{}], bk_obj_id: {}.".format(asset_name, bk_obj_id))
            platform = Platform.objects.filter(name='Website').first()
            asset_protocol = ["http/443"]

            if bk_obj_id == 'storage_oss' and manufacturer in ['EMC']:
                address = storage_cls + '/#/dashboard'
            elif bk_obj_id == 'storage_oss' and manufacturer in ['XSKY']:
                address = storage_cls + '/login?redirect=dashboard'
            elif bk_obj_id == 'storage_oss' and manufacturer in ['华为', '浪潮']:
                address = storage_cls + '/#/login'
            elif bk_obj_id == 'fc_storage' and manufacturer in ['EMC']:
                address = storage_cls + '/cas/login'
            elif bk_obj_id == 'fc_storage' and manufacturer in ['H3C', '华为']:
                address = storage_cls + '/login'
            elif bk_obj_id == 'network_storage' and manufacturer in ['NetApp']:
                address = storage_cls + '/sysmgr/v4'
            elif bk_obj_id == 'network_storage' and manufacturer in ['华为']:
                address = storage_cls + '/deviceManager/devicemanager/feature/login/login.html'
            else:
                address = storage_cls + '/'

            comment = bk_obj_id + '-' + storage_cls

            # 用户确认全平台主机名唯一
            assetList = Asset.objects.filter(name=asset_name)
            if not assetList.exists():
                a = Asset.objects.create(name=asset_name,
                                         address=address,
                                         platform=platform,
                                         comment=comment,
                                         org_id=org.id)

                asset_model = get_web_asset_model(bk_obj_id, manufacturer, asset, a)
                asset_model.__dict__.update(a.__dict__)
                asset_model.save()

                key = f"{str(org.id)}_{a.name}"
                asset_org_dict.update({key: a.id})
                create_asset_node(full_assetnode_name, a)
                relate_protocols(asset_protocol, a)
                print("Success to create pc host asset[{}].".format(asset_name))
                continue

            for a in assetList:
                # 更新资产信息
                # 如果平台不同，先删再加
                if a.platform_id != platform.id:
                    p = Platform.objects.get(id=a.platform_id)
                    if p.type != platform.type:
                        Asset.objects.get(id=a.id).delete()
                        print("Incompatible platform: old-[{}], new-[{}]; Delete pc host asset[{}], create it."
                              .format(p.name, platform.name, asset_name))

                        a = Asset.objects.create(name=asset_name,
                                                 address=address,
                                                 platform=platform,
                                                 comment=comment,
                                                 org_id=org.id)

                        asset_model = get_web_asset_model(bk_obj_id, manufacturer, asset, a)
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()
                        print("Success to create pc host asset[{}].".format(asset_name))
                else:
                    a.address = address
                    a.comment = comment
                    a.save()

                    asset_model = update_web_asset_model(bk_obj_id, manufacturer, asset, a)
                    asset_model.__dict__.update(a.__dict__)
                    asset_model.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to update pc host asset[{}].".format(asset_name))
        except Exception as e:
            print("Failed to save pc host asset[{}], error:{}".format(asset_name, e))
            raise e


def update_web_asset_model(bk_obj_id, manufacturer, asset, a):
    asset_model = Web.objects.get(asset_ptr_id=a.id)

    if bk_obj_id == 'mid_bes':
        instance_type = asset.get('instance_type', '')
        if instance_type:
            # 3 集群版、4 单实例版
            if instance_type == '3':
                asset_model.autofill = 'basic'
                asset_model.username_selector = 'id=j_username'
                asset_model.password_selector = 'id=j_password'
                asset_model.submit_selector = ''
            else:
                asset_model.autofill = 'basic'
                asset_model.username_selector = 'id=j_username'
                asset_model.password_selector = 'id=plainPassword'
                asset_model.submit_selector = ''
        else:
            asset_model.autofill = 'no'
    elif bk_obj_id == 'mid_mq':
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'name=username'
        asset_model.password_selector = 'name=password'
        asset_model.submit_selector = ''
        # asset_model.submit_selector = 'xpath=//*[@id="login"]/form/table/tbody/tr[3]/td/input'
    elif bk_obj_id == 'weblogic_inst':
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=j_username'
        asset_model.password_selector = 'id=j_password'
        asset_model.submit_selector = ''
        # asset_model.submit_selector = 'xpath=//*[@id="loginData"]/div[4]/span/input'
    elif bk_obj_id == 'pc_server' and manufacturer in ['IBM', '百信', '宝德', '超聚变', '广电五舟', '宝德', '华鲲振宇', '神州鲲泰', '天宫']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=account'
        asset_model.password_selector = 'id=loginPwd'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'pc_server' and manufacturer in ['安擎', '百信恒山', '鼎甲', '华为泰山', '清华同方', '神州云科', '四川虹信', '长江计算']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=login_name'
        asset_model.password_selector = 'id=login_pwd'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'pc_server' and manufacturer in ['联想']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=login_username'
        asset_model.password_selector = 'id=login_password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'pc_server' and manufacturer in ['华为']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=iptUserName'
        asset_model.password_selector = 'id=iptPassword'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'pc_server' and manufacturer in ['曙光', '长城', '中科可控', '中科曙光', '中兴', '神州云科', '四川虹信']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=userid'
        asset_model.password_selector = 'id=password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'pc_server' and manufacturer in ['新华三']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=username'
        asset_model.password_selector = 'id=password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'pc_server' and manufacturer in ['惠普', '浪潮', '浪潮商用', '紫光']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'name=username'
        asset_model.password_selector = 'name=password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'pc_server' and manufacturer in ['超微']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'name=name'
        asset_model.password_selector = 'name=pwd'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'storage_oss' and manufacturer in ['EMC']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=user'
        asset_model.password_selector = 'id=password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'storage_oss' and manufacturer in ['XSKY']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'name=name'
        asset_model.password_selector = 'name=password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'storage_oss' and manufacturer in ['华为']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=login_loginPanel_username_input'
        asset_model.password_selector = 'id=login_loginPanel_password_input'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'storage_oss' and manufacturer in ['浪潮']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=user'
        asset_model.password_selector = 'xpath=/html/body/div[1]/div/div/div[3]/div[2]/div[2]/form/input[2]'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'fc_storage' and manufacturer in ['EMC', 'IBM', '浪潮']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=user'
        asset_model.password_selector = 'id=password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'fc_storage' and manufacturer in ['华为']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=login_loginPanel_username_input'
        asset_model.password_selector = 'id=login_loginPanel_password_input'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'fc_storage' and manufacturer in ['H3C']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'xpath=//*[@id="content"]/div/div[2]/div[2]/div/div/div/div[3]/div/form/div[1]/div[1]/div/div/input'
        asset_model.password_selector = 'xpath=//*[@id="content"]/div/div[2]/div[2]/div/div/div/div[3]/div/form/div[1]/div[2]/div/div/input'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'network_storage' and manufacturer in ['NetApp']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'name=name'
        asset_model.password_selector = 'name=password'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'network_storage' and manufacturer in ['华为']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=userName'
        asset_model.password_selector = 'id=passWord'
        asset_model.submit_selector = ''
    elif bk_obj_id == 'network_storage' and manufacturer in ['浪潮']:
        asset_model.autofill = 'basic'
        asset_model.username_selector = 'id=user'
        asset_model.password_selector = 'id=password'
        asset_model.submit_selector = ''
    else:
        asset_model.autofill = 'no'

    return asset_model


def get_web_asset_model(bk_obj_id, manufacturer, asset, a):
    if bk_obj_id == 'mid_bes':
        instance_type = asset.get('instance_type', '')
        if instance_type:
            # 3 集群版、4 单实例版
            if instance_type == '3':
                asset_model = Web(
                    asset_ptr_id=a.id,
                    autofill='basic',
                    username_selector='id=j_username',
                    password_selector='id=j_password',
                    submit_selector=''
                )
            else:
                asset_model = Web(
                    asset_ptr_id=a.id,
                    autofill='basic',
                    username_selector='id=j_username',
                    password_selector='id=plainPassword',
                    submit_selector=''
                )
        else:
            asset_model = Web(asset_ptr_id=a.id, autofill='no')
    elif bk_obj_id == 'mid_mq':
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='name=username',
            password_selector='name=password',
            submit_selector=''
        )
            # submit_selector='xpath=//*[@id="login"]/form/table/tbody/tr[3]/td/input'
    elif bk_obj_id == 'weblogic_inst':
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=j_username',
            password_selector='id=j_password',
            submit_selector=''
        )
            # submit_selector='xpath=//*[@id="loginData"]/div[4]/span/input'
    elif bk_obj_id == 'pc_server' and manufacturer in ['IBM', '百信', '宝德', '超聚变', '广电五舟', '华鲲振宇', '神州鲲泰', '天宫']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=account',
            password_selector='id=loginPwd',
            submit_selector=''
        )
    elif bk_obj_id == 'pc_server' and manufacturer in ['安擎', '百信恒山', '鼎甲', '华为泰山', '清华同方', '神州云科', '四川虹信', '长江计算']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=login_name',
            password_selector='id=login_pwd',
            submit_selector=''
        )
    elif bk_obj_id == 'pc_server' and manufacturer in ['联想', '英伟达']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=login_username',
            password_selector='id=login_password',
            submit_selector=''
        )
    elif bk_obj_id == 'pc_server' and manufacturer in ['华为']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=iptUserName',
            password_selector='id=iptPassword',
            submit_selector=''
        )
    elif bk_obj_id == 'pc_server' and manufacturer in ['曙光', '长城', '中科可控', '中科曙光', '中兴', '神州云科', '四川虹信']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=userid',
            password_selector='id=password',
            submit_selector=''
        )
    elif bk_obj_id == 'pc_server' and manufacturer in ['新华三']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=username',
            password_selector='id=password',
            submit_selector=''
        )
    elif bk_obj_id == 'pc_server' and manufacturer in ['惠普', '浪潮', '浪潮商用', '紫光']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='name=username',
            password_selector='name=password',
            submit_selector=''
        )
    elif bk_obj_id == 'pc_server' and manufacturer in ['超微']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='name=name',
            password_selector='name=pwd',
            submit_selector=''
        )
    elif bk_obj_id == 'storage_oss' and manufacturer in ['EMC']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=user',
            password_selector='id=password',
            submit_selector=''
        )
    elif bk_obj_id == 'storage_oss' and manufacturer in ['XSKY']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='name=name',
            password_selector='name=password',
            submit_selector=''
        )
    elif bk_obj_id == 'storage_oss' and manufacturer in ['华为']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=login_loginPanel_username_input',
            password_selector='id=login_loginPanel_password_input',
            submit_selector=''
        )
    elif bk_obj_id == 'storage_oss' and manufacturer in ['浪潮']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=user',
            password_selector='xpath=/html/body/div[1]/div/div/div[3]/div[2]/div[2]/form/input[2]',
            submit_selector=''
        )
    elif bk_obj_id == 'fc_storage' and manufacturer in ['EMC', 'IBM', '浪潮']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=user',
            password_selector='id=password',
            submit_selector=''
        )
    elif bk_obj_id == 'fc_storage' and manufacturer in ['华为']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=login_loginPanel_username_input',
            password_selector='id=login_loginPanel_password_input',
            submit_selector=''
        )
    elif bk_obj_id == 'fc_storage' and manufacturer in ['H3C']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='xpath=//*[@id="content"]/div/div[2]/div[2]/div/div/div/div[3]/div/form/div[1]/div[1]/div/div/input',
            password_selector='xpath=//*[@id="content"]/div/div[2]/div[2]/div/div/div/div[3]/div/form/div[1]/div[2]/div/div/input',
            submit_selector=''
        )
    elif bk_obj_id == 'network_storage' and manufacturer in ['NetApp']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='name=name',
            password_selector='name=password',
            submit_selector=''
        )
    elif bk_obj_id == 'network_storage' and manufacturer in ['华为']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=userName',
            password_selector='id=passWord',
            submit_selector=''
        )
    elif bk_obj_id == 'network_storage' and manufacturer in ['浪潮']:
        asset_model = Web(
            asset_ptr_id=a.id,
            autofill='basic',
            username_selector='id=user',
            password_selector='id=password',
            submit_selector=''
        )
    else:
        asset_model = Web(asset_ptr_id=a.id, autofill='no')

    return asset_model


# 所有PC机归属系统管理室
def save_pc_host_asset(assets, asset_org_dict, isFullSync, bk_obj_id):
    org = Organization.objects.get(id=Organization.DEFAULT_ID)
    set_current_org(org)

    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync:
            if not compare_time(update_time):
                continue

        asset_name = asset.get('bk_inst_name', '')
        sys_name = asset.get('sys_name', '')
        haddr_ip_address = asset.get('haddr_ip_address', '')
        # app_department = asset.get('app_department', '')   # 应用部门
        manufacturer = asset.get('manufacturer', '')   # 厂商
        status = asset.get('status', '') # 配置状态
        # 未维护信息过滤掉
        if not asset_name or not manufacturer or not haddr_ip_address:
            print("There exist null parameter situations, skip.")
            continue
        # 运行、运行(不买保)
        if not str(status).__contains__('运行'):
            continue

        full_assetnode_name = "/" + org.name
        if sys_name:
            full_assetnode_name = full_assetnode_name + "/" + sys_name

        try:
            print("Save or update pc host asset[{}].".format(asset_name))
            platform = Platform.objects.filter(name='Website').first()
            asset_protocol = ["http/443"]
            if str(haddr_ip_address).__contains__('http'):
                haddr_ip_address = extract_ip_from_url(haddr_ip_address)

            if manufacturer in ['IBM', '百信']:
                address = 'https://' + haddr_ip_address + '/UI/Static/#/login'
            elif manufacturer in ['安擎', '百信恒山', '宝德', '超聚变', '鼎甲', '广电五舟', '华鲲振宇', '华为泰山', '清华同方',
                                  '神州鲲泰', '神州云科', '曙光', '四川虹信', '天宫', '长城', '长江计算', '中科可控', '中科曙光',
                                  '中兴', '紫光']:
                address = 'https://' + haddr_ip_address + '/#/login'
            elif manufacturer in ['新华三']:
                address = 'https://' + haddr_ip_address + '/user/login'
            else:
                # ['超微', '华为', '惠普', '浪潮', '浪潮商用', '联想', '英伟达']
                address = 'https://' + haddr_ip_address + '/'
                # 其它  ['ZDNS', '戴尔']

            comment = bk_obj_id + '-' + haddr_ip_address

            # 用户确认全平台主机名唯一
            assetList = Asset.objects.filter(name=asset_name)
            if not assetList.exists():
                a = Asset.objects.create(name=asset_name,
                                         address=address,
                                         platform=platform,
                                         comment=comment,
                                         org_id=org.id)

                asset_model = get_web_asset_model(bk_obj_id, manufacturer, asset, a)
                asset_model.__dict__.update(a.__dict__)
                asset_model.save()

                key = f"{str(org.id)}_{a.name}"
                asset_org_dict.update({key: a.id})
                create_asset_node(full_assetnode_name, a)
                relate_protocols(asset_protocol, a)
                print("Success to create pc host asset[{}].".format(asset_name))
                continue

            for a in assetList:
                # 更新资产信息
                # 如果平台不同，先删再加
                if a.platform_id != platform.id:
                    p = Platform.objects.get(id=a.platform_id)
                    if p.type != platform.type:
                        Asset.objects.get(id=a.id).delete()
                        print("Incompatible platform: old-[{}], new-[{}]; Delete pc host asset[{}], create it."
                              .format(p.name, platform.name, asset_name))

                        a = Asset.objects.create(name=asset_name,
                                                 address=address,
                                                 platform=platform,
                                                 comment=comment,
                                                 org_id=org.id)

                        asset_model = get_web_asset_model(bk_obj_id, manufacturer, asset, a)
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()
                        print("Success to create pc host asset[{}].".format(asset_name))
                else:
                    a.address = address
                    a.comment = comment
                    a.save()

                    asset_model = update_web_asset_model(bk_obj_id, manufacturer, asset, a)
                    asset_model.__dict__.update(a.__dict__)
                    asset_model.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to update pc host asset[{}].".format(asset_name))
        except Exception as e:
            print("Failed to save pc host asset[{}], error:{}".format(asset_name, e))
            raise e


def extract_ip_from_url(haddr_ip_address):
    """
    从各种格式的URL中提取纯IP地址
    支持：http://ip、http://ip/、https://ip/path、ip:port等格式
    """
    # 1. 解析URL，拆分协议、域名/IP、路径等部分
    parsed_url = urlparse(haddr_ip_address)

    # 2. 获取网络位置部分（就是IP/域名，自动去掉协议、路径、末尾斜杠）
    netloc = parsed_url.netloc

    # 3. 处理特殊情况：如果URL没有协议（如10.10.11.1），urlparse会识别到path中
    if not netloc:
        netloc = parsed_url.path.split('/')[0]  # 截取/前面的部分

    # 4. 正则匹配纯IP（支持IPv4，去掉端口号如10.10.11.1:8080）
    ip_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    match = re.search(ip_pattern, netloc)

    return match.group(1) if match else None


def save_host_asset(assets, asset_org_dict, user_org_dict, isFullSync):
    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync:
            if not compare_time(update_time):
                continue

        sys_number = asset.get('sys_number', '')
        sys_name = asset.get('sys_name', '')
        asset_name = asset.get('bk_host_name', '')
        address = asset.get('bk_host_innerip', '')
        bk_os_type = asset.get('bk_os_type', '')
        org_name = asset.get('app_department', '')
        # 运维人员组织架构  获取的是[1290]  根据id查询用户归属组织名称
        user_org_id = asset.get('user_org', '')
        default_user_org_name = '系统管理室'
        user_org_name = search_user_org_name(user_org_id, user_org_dict, default_user_org_name)

        if asset_name:
            asset_name = asset_name + '_' + address
        else:
            asset_name = address + '_' + bk_os_type

        # 在 Default 组织下管理所有资产，在归属部门 app_department 对应组织下管理关联资产
        orgs = []
        org_asset_comment_dict = {}
        if len(org_name) > 0:
            # 太平金科-系统运行与信息安全管理部 特殊处理
            dept_name = '系统运行与信息安全管理部'
            if str(org_name) == dept_name:
                # 应用科室
                app_office = asset.get('app_office', '')

                if not user_org_name:
                    # 系统运行与信息安全管理部-系统管理室
                    org = Organization.objects.get(id=Organization.DEFAULT_ID)
                    orgs.append(org)
                    org_asset_comment_dict[org.id] = default_user_org_name

                    # 在应用科室归属组织下创建资产
                    relate_app_office_org(app_office, dept_name, orgs, org_asset_comment_dict, default_user_org_name,
                                          asset_name)
                else:
                    name = '系统运行与信息安全管理部-' + user_org_name
                    org = Organization.objects.filter(name=name).first()
                    if org:
                        orgs.append(org)
                        org_asset_comment_dict.update({org.id: user_org_name})
                    else:
                        print("堡垒机上不存在组织[{}]，asset_name: {}.".format(name, asset_name))
                        org = Organization.objects.create(name=name)
                        orgs.append(org)
                        org_asset_comment_dict[org.id] = user_org_name
                        print("Success to create org[{}].".format(name))

                    # 在应用科室归属组织下创建资产
                    relate_app_office_org(app_office, dept_name, orgs, org_asset_comment_dict, user_org_name,
                                          asset_name)
            else:
                if user_org_name:
                    if str(user_org_name) == default_user_org_name:
                        # 系统运行与信息安全管理部-系统管理室
                        org = Organization.objects.get(id=Organization.DEFAULT_ID)
                        orgs.append(org)
                        org_asset_comment_dict[org.id] = user_org_name
                else:
                    org = Organization.objects.get(id=Organization.DEFAULT_ID)
                    orgs.append(org)
                    org_asset_comment_dict[org.id] = default_user_org_name

                # 所属应用部门
                org = Organization.objects.filter(name=org_name).first()
                if org:
                    orgs.append(org)
                    org_asset_comment_dict[org.id] = user_org_name
                else:
                    print("堡垒机上不存在组织[{}]，asset_name: {}.".format(org_name, asset_name))
                    org = Organization.objects.create(name=org_name)
                    orgs.append(org)
                    org_asset_comment_dict[org.id] = user_org_name
                    print("Success to create org[{}].".format(org_name))

        try:
            print("Save or update host asset[{}].".format(asset_name))
            if bk_os_type == '1':
                asset_protocol = ["ssh/22", "sftp/22"]
                platform = Platform.objects.filter(name='Linux').first()
            elif bk_os_type == '2':
                asset_protocol = ["rdp/3389"]
                bk_os_name = asset.get('bk_os_name', '')
                if bk_os_name and str(bk_os_name).__contains__('2016'):
                    platform = Platform.objects.filter(name='Windows2016').first()
                else:
                    platform = Platform.objects.filter(name='Windows').first()
            elif bk_os_type == '3':
                asset_protocol = ["ssh/22", "telnet/23"]
                platform = Platform.objects.filter(name='AIX').first()
            else:
                print("bk_os_type[{}] is not exist, skip.".format(bk_os_type))
                continue

            for org in orgs:
                set_current_org(org)

                full_assetnode_name = "/" + org.name
                if sys_number and sys_name:
                    assetnode_name = sys_number + '-' + sys_name
                    full_assetnode_name = full_assetnode_name + "/" + assetnode_name

                # 用户确认全平台主机名唯一
                assetList = Asset.objects.filter(name=asset_name)
                if not assetList.exists():
                    a = Asset.objects.create(name=asset_name,
                                             address=address,
                                             platform=platform,
                                             org_id=org.id,
                                             comment=org_asset_comment_dict.get(org.id, ''))

                    asset_model = Host(asset_ptr_id=a.id)
                    asset_model.__dict__.update(a.__dict__)
                    asset_model.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to create host asset[{}].".format(asset_name))
                    continue

                for a in assetList:
                    # 更新资产信息
                    # 如果平台不同，先删再加
                    if a.platform_id != platform.id:
                        print(a.type)
                        p = Platform.objects.get(id=a.platform_id)
                        if p.type != platform.type:
                            Asset.objects.get(id=a.id).delete()
                            print("Incompatible platform: old-[{}], new-[{}]; Delete host asset[{}], create it.".format(p.name, platform.name, asset_name))

                            a = Asset.objects.create(name=asset_name,
                                                     address=address,
                                                     platform=platform,
                                                     org_id=org.id,
                                                     comment=org_asset_comment_dict.get(org.id, ''))

                            asset_model = Host(asset_ptr_id=a.id)
                            asset_model.__dict__.update(a.__dict__)
                            asset_model.save()
                            print("Success to create host asset[{}].".format(asset_name))
                    else:
                        a.address = address
                        a.comment = org_asset_comment_dict.get(org.id, '')
                        a.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to update host asset[{}].".format(asset_name))
        except Exception as e:
            print("Failed to save host asset[{}], error:{}".format(asset_name, e))
            raise e


def relate_app_office_org(app_office, dept_name, orgs, org_asset_comment_dict, user_org_name, asset_name):
    if app_office:
        # 应用科室所属组织
        app_office_org_name = dept_name + '-' + app_office
        org = Organization.objects.filter(name=app_office_org_name).first()
        if org:
            orgs.append(org)
            org_asset_comment_dict.update({org.id: user_org_name})
        else:
            print("堡垒机上不存在组织[{}]，asset_name: {}.".format(app_office_org_name, asset_name))
            org = Organization.objects.create(name=app_office_org_name)
            orgs.append(org)
            org_asset_comment_dict[org.id] = user_org_name
            print("Success to create org[{}].".format(app_office_org_name))


def relate_protocols(string, asset):
    try:
        if len(string) > 0:
            for protocol in string:
                arr = str(protocol).lower().split("/")
                protocols = Protocol.objects.filter(name=arr[0], port=arr[1], asset_id=asset.id)
                if not protocols.exists():
                    Protocol.objects.create(name=arr[0], port=arr[1], asset_id=asset.id)
    except Exception as e:
        print("Relate asset[{}]'s protocols error:{}".format(asset.name, e))


def create_asset_node(assetnode_name, asset):
    if len(assetnode_name) > 0:
        node = Node.objects.filter(full_value=assetnode_name).first()
        if not node:
            full_value = ''
            for index, value in enumerate(assetnode_name.split("/")):
                if index > 0:
                    full_value = full_value + '/' + value
                    asset_node = get_object_or_none(Node, full_value=full_value)
                    if not asset_node:
                        if index == 1:
                            print("Root node[{}] does not exist!".format(value))
                            break
                        else:
                            node.get_or_create_child(value=value)

                    node = Node.objects.filter(full_value=full_value).first()

        if node:
            asset.nodes.set([node.id])

def search_other_asset(bk_obj_id, region):
    bk_token = Login(username=settings.CMDB_USERNAME, password=settings.CMDB_PASSWORD).login()
    print(f'bk_token: {bk_token}')
    if not bk_token:
        print("获取bk_token失败.")
        return

    limit = 500
    CMDB_HEADERS = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    url = "{CMDB_SERVER}/api/c/compapi/v2/cc/search_inst/".format(CMDB_SERVER=settings.CMDB_BK_PAAS_HOST)

    data = {
        "bk_app_code": settings.CMDB_BK_APP_CODE,
        "bk_app_secret": settings.CMDB_BK_APP_SECRET,
        "bk_token": bk_token,
        "bk_obj_id": bk_obj_id,
        "page": {
            "start": 0,
            "limit": limit
        },
        "condition": {
            bk_obj_id: [
                {
                    "field": "region",
                    "operator": "$eq",
                    "value": region
                }
            ]
        }
    }

    print("url: {}".format(url))
    print("data: {}".format(json.dumps(data)))

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "request_id": "",
        "data": {
            "total": 0,
            "list": []
        }
    }

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        data["page"]["start"] = (current_page - 1) * limit
        r = requests.post(url, headers=CMDB_HEADERS, json=data, timeout=10)
        response = r.json()
        code = response["code"]

        if code != 0:
            message = response["message"]
            print("Search other asset failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            result["request_id"] = response["request_id"]
            return result

        res = response["data"]
        total_pages = res["count"] // limit + (1 if res["count"] % limit != 0 else 0)

        result["data"]["total"] = res["count"]
        result["data"]["list"].extend(res["info"])
        current_page += 1

    # print("bk_obj_id: {}, search_RES: {}".format(bk_obj_id, json.dumps(result)))
    return result


def search_other_asset_no_region(bk_obj_id):
    bk_token = Login(username=settings.CMDB_USERNAME, password=settings.CMDB_PASSWORD).login()
    print(f'bk_token: {bk_token}')
    if not bk_token:
        print("获取bk_token失败.")
        return

    limit = 500
    CMDB_HEADERS = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    url = "{CMDB_SERVER}/api/c/compapi/v2/cc/search_inst/".format(CMDB_SERVER=settings.CMDB_BK_PAAS_HOST)

    data = {
        "bk_app_code": settings.CMDB_BK_APP_CODE,
        "bk_app_secret": settings.CMDB_BK_APP_SECRET,
        "bk_token": bk_token,
        "bk_obj_id": bk_obj_id,
        "page": {
            "start": 0,
            "limit": limit
        }
    }

    print("url: {}".format(url))
    print("data: {}".format(json.dumps(data)))

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "request_id": "",
        "data": {
            "total": 0,
            "list": []
        }
    }

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        data["page"]["start"] = (current_page - 1) * limit
        r = requests.post(url, headers=CMDB_HEADERS, json=data, timeout=10)
        response = r.json()
        code = response["code"]

        if code != 0:
            message = response["message"]
            print("Search other asset failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            result["request_id"] = response["request_id"]
            return result

        res = response["data"]
        total_pages = res["count"] // limit + (1 if res["count"] % limit != 0 else 0)

        result["data"]["total"] = res["count"]
        result["data"]["list"].extend(res["info"])
        current_page += 1

    # print("bk_obj_id: {}, search_RES: {}".format(bk_obj_id, json.dumps(result)))
    return result


def search_host_asset():
    bk_token = Login(username=settings.CMDB_USERNAME, password=settings.CMDB_PASSWORD).login()
    print(f'bk_token: {bk_token}')
    if not bk_token:
        print("获取bk_token失败.")
        return

    limit = 500
    CMDB_HEADERS = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    url = "{CMDB_SERVER}/api/c/compapi/v2/cc/list_hosts_without_biz/".format(CMDB_SERVER=settings.CMDB_BK_PAAS_HOST)

    # 2 开发测试
    data = {
        "bk_app_code": settings.CMDB_BK_APP_CODE,
        "bk_app_secret": settings.CMDB_BK_APP_SECRET,
        "bk_token": bk_token,
        "bk_supplier_account": "0",
        "page": {
            "start": 0,
            "limit": limit
        },
        "host_property_filter": {
            "condition": "AND",
            "rules": [
                {
                    "field": "region",
                    "operator": "in",
                    "value": ["1", "3", "4", "5", "7"]
                }
            ]
        }
    }

    print("url: {}".format(url))
    print("data: {}".format(json.dumps(data)))

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "request_id": "",
        "data": {
            "total": 0,
            "list": []
        }
    }

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        data["page"]["start"] = (current_page - 1) * limit
        r = requests.post(url, headers=CMDB_HEADERS, json=data, timeout=10)
        response = r.json()
        code = response["code"]

        if code != 0:
            message = response["message"]
            print("Search host asset failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            result["request_id"] = response["request_id"]
            return result

        res = response["data"]
        total_pages = res["count"] // limit + (1 if res["count"] % limit != 0 else 0)

        result["data"]["total"] = res["count"]
        result["data"]["list"].extend(res["info"])
        current_page += 1

    # print("search_host_asset_RES: {}".format(json.dumps(result)))
    return result


def search_user_org_name(id, user_org_dict, default_user_org_name):
    # 如果 id 是列表，就取第一个元素
    if isinstance(id, list):
        # 列表为空也返回默认值
        if not id:
            return default_user_org_name
        id = id[0]

    if not id:
        return default_user_org_name

    bk_token = Login(username=settings.CMDB_USERNAME, password=settings.CMDB_PASSWORD).login()
    print(f'bk_token: {bk_token}')
    if not bk_token:
        print("获取bk_token失败.")
        return

    CMDB_HEADERS = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    url = "{CMDB_SERVER}/api/c/compapi/v2/usermanage/retrieve_department/".format(CMDB_SERVER=settings.CMDB_BK_PAAS_HOST)

    data = {
        "bk_app_code": settings.CMDB_BK_APP_CODE,
        "bk_app_secret": settings.CMDB_BK_APP_SECRET,
        "bk_token": bk_token,
        "id": id,
        "fields": "name,id"
    }

    print("url: {}".format(url))
    print("data: {}".format(json.dumps(data)))

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "request_id": ""
    }

    r = requests.post(url, headers=CMDB_HEADERS, json=data, timeout=10)
    response = r.json()
    code = response["code"]

    if code != 0:
        message = response["message"]
        print("Search user org name failed. , Error: {}".format(message))
        result["code"] = code
        result["error"] = message
        result["request_id"] = response["request_id"]
        print(result)
        return default_user_org_name

    res = response["data"]["name"]
    user_org_dict.update({id: res})
    return res


def compare_time(time_str: str) -> bool:
    if not time_str:
        return False

    try:
        # 1. 把标准ISO时间字符串转成带时区的时间 → 时间戳A
        dt = datetime.fromisoformat(time_str)
        timestamp_a = dt.timestamp()

        # 2. 以该时间为基准，计算cron上一次执行时间 → 时间戳B
        cron_expr = settings.CMDB_INCREMENTAL_DATA_SYNC_CRONTAB
        now = datetime.now()
        cron = croniter.croniter(cron_expr, now)
        last_exec_dt = cron.get_prev(datetime)
        timestamp_b = last_exec_dt.timestamp()

        # 3. 对比返回
        return timestamp_a > timestamp_b
    except Exception as e:
        print("time_str: {}, compare_time error: {}".format(time_str, e))
        return True



class Login(object):
    """
    导入用户
    """

    def __init__(self, username=None, password=None):
        super(Login, self).__init__()
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({'referer': "%s" % settings.CMDB_BK_PAAS_HOST})
        self.session.verify = False

    def get_csrftoken(self, url, token_name):
        resp = self.session.get(url, verify=False)
        if resp.status_code == 200:
            return resp.cookies[token_name]

    def login(self, login_url=None):
        login_url = login_url or settings.CMDB_BK_PAAS_HOST + '/login/?bk_login=1/'
        # login_url = login_url or BK_PAAS_HOST
        login_csrftoken = self.get_csrftoken(login_url, 'bklogin_csrftoken')
        login_form = {
            'csrfmiddlewaretoken': login_csrftoken,
            'username': self.username,
            'password': self.password
        }
        resp = self.session.post(login_url, data=login_form, verify=False)
        print(f'login_csrftoken: {login_csrftoken}')
        print(f'username: {self.username}')

        if resp.status_code == 200:
            return resp.request.headers['Cookie'].split('bk_token=')[1].split(';')[0]
        return ""
