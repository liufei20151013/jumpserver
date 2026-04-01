import uuid

import requests
import json

from orgs.utils import set_current_org

from orgs.models import Organization
from assets.models import Asset, Platform, Database, Node, Host, Protocol, Device
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

    bk_token = Login(username=settings.CMDB_USERNAME, password=settings.CMDB_PASSWORD).login()
    print(f'bk_token: {bk_token}')
    if not bk_token:
        print("获取bk_token失败.")
        return

    if isFullSync:
        print("获取堡垒机上原始资产数据 Start.")
        old_asset_org_dict = {}
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

    print("查询所有主机资产 Start.")
    result = search_host_asset(bk_token)
    if result['code'] != 0:
        print("查询 CMDB 主机数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
        return

    host_data = result['data']['list']
    print("查询 CMDB 主机数据成功，total: {} 条".format(len(host_data)))

    save_host_asset(host_data, asset_org_dict, isFullSync)
    print("查询所有主机资产 End.")

    print("查询网络设备 Start.")
    objects = {
        "network_device": "网络设备"
    }
    for bk_obj_id, bk_obj_name in objects.items():
        print("查询 bk_obj_id: {}, bk_obj_name: {}".format(bk_obj_id, bk_obj_name))
        result = search_other_asset(bk_token, bk_obj_id)
        if result['code'] != 0:
            print("查询 CMDB 网络设备数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
            return

        network_device_data = result['data']['list']
        print("查询 bk_obj_id: {}, bk_obj_name: {}，total: {} 条".format(bk_obj_id, bk_obj_name, len(network_device_data)))

        save_network_device_asset(network_device_data, asset_org_dict, isFullSync)
    print("查询所有网络设备 End.")

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
        print("查询 bk_obj_id: {}, bk_obj_name: {}".format(bk_obj_id, bk_obj_name))
        result = search_other_asset(bk_token, bk_obj_id, isFullSync)
        if result['code'] != 0:
            print("查询 CMDB 数据库资产数据失败，code: {}, requestId: {}".format(result['code'], result['request_id']))
            return

        db_data = result['data']['list']
        print("查询 bk_obj_id: {}, bk_obj_name: {}，total: {}条".format(bk_obj_id, bk_obj_name, len(db_data)))

        save_db_asset(db_data, asset_org_dict, bk_obj_id)
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


def save_db_asset(assets, asset_org_dict, bk_obj_id, isFullSync):
    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync and compare_time(update_time):
            continue

        sys_number = asset.get('sys_number', '')
        sys_name = asset.get('sys_name', '')
        asset_name = asset.get('bk_inst_name', '')
        ip_addr = asset.get('ip_addr', '')
        db_port = asset.get('port', '')
        org_name = asset.get('app_department', '')
        # 未维护信息过滤掉
        if not sys_number or not sys_name or not asset_name or not ip_addr or not db_port or not org_name:
            continue
        assetnode_name = sys_number + '-' + sys_name

        # 在 Default 组织下管理所有资产，在归属部门 app_department 对应组织下管理关联资产
        DEFAULT_ORG = Organization.objects.get(id=Organization.DEFAULT_ID)
        orgs = [DEFAULT_ORG]
        org = Organization.objects.filter(name=org_name).first()
        if org:
            orgs.append(org)
        else:
            print("堡垒机上不存在组织[{}]，请新建组织后全量同步，asset_name: {}.".format(org_name, asset_name))
            continue


        try:
            print("Save or update db asset[{}].".format(asset_name))
            default_db = ''
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
                continue


            if not platform:
                print("asset[{}]'s platform is not exist, bk_obj_id: {}.".format(asset_name, bk_obj_id))
                continue

            asset_protocol = []
            asset_protocol.append(protocol)

            for org in orgs:
                set_current_org(org)
                full_assetnode_name = "/" + org.name + "/" + assetnode_name

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

# 所有的网络设备都同步到太平金科组织下
def save_network_device_asset(assets, asset_org_dict, isFullSync):
    org = Organization.objects.get(id=Organization.DEFAULT_ID)
    set_current_org(org)

    assetnode_name = '/' + org.name
    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync and compare_time(update_time):
            continue

        asset_name = asset.get('bk_inst_name', '')
        address = asset.get('ip_address', '')
        manufacturer = asset.get('manufacturer', '')
        # 未维护信息过滤掉
        if not asset_name or not address or not manufacturer:
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


def save_host_asset(assets, asset_org_dict, isFullSync):
    for asset in assets:
        update_time = asset.get('last_time') or asset.get('create_time')
        if not isFullSync and compare_time(update_time):
            continue

        sys_number = asset.get('sys_number', '')
        sys_name = asset.get('sys_name', '')
        asset_name = asset.get('bk_host_name', '')
        address = asset.get('bk_host_innerip', '')
        bk_os_type = asset.get('bk_os_type', '')
        org_name = asset.get('app_department', '')
        if not sys_number or not sys_name or not asset_name or not address or not bk_os_type or not org_name:
            continue
        assetnode_name = sys_number + '-' + sys_name

        # 在 Default 组织下管理所有资产，在归属部门 app_department 对应组织下管理关联资产
        org = Organization.objects.get(id=Organization.DEFAULT_ID)
        orgs = [org]
        if len(org_name) > 0:
            org = Organization.objects.filter(name=org_name).first()
            if org:
                orgs.append(org)
            else:
                print("堡垒机上不存在组织[{}]，请新建组织后全量同步，asset_name: {}.".format(org_name, asset_name))
                continue

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
                continue

            for org in orgs:
                set_current_org(org)
                full_assetnode_name = "/" + org.name + "/" + assetnode_name

                # 用户确认全平台主机名唯一
                assetList = Asset.objects.filter(name=asset_name)
                if not assetList.exists():
                    a = Asset.objects.create(name=asset_name,
                                             address=address,
                                             platform=platform,
                                             org_id=org.id)

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
                                                     org_id=org.id)

                            asset_model = Host(asset_ptr_id=a.id)
                            asset_model.__dict__.update(a.__dict__)
                            asset_model.save()
                            print("Success to create host asset[{}].".format(asset_name))
                    else:
                        a.address = address
                        a.save()

                    key = f"{str(org.id)}_{a.name}"
                    asset_org_dict.update({key: a.id})
                    create_asset_node(full_assetnode_name, a)
                    relate_protocols(asset_protocol, a)
                    print("Success to update host asset[{}].".format(asset_name))
        except Exception as e:
            print("Failed to save host asset[{}], error:{}".format(asset_name, e))
            raise e


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

def search_other_asset(bk_token, bk_obj_id):
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
        "host_property_filter": {
            "condition": "AND",
            "rules": [
                {
                    "field": "region",
                    "operator": "in",
                    "value": ["1", "3", "4"]
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


def search_host_asset(bk_token):
    limit = 500
    CMDB_HEADERS = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    url = "{CMDB_SERVER}/api/c/compapi/v2/cc/list_hosts_without_biz/".format(CMDB_SERVER=settings.CMDB_BK_PAAS_HOST)

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
                    "value": ["1", "3", "4"]
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


def compare_time(time_str: str) -> bool:
    if not time_str:
        return False

    try:
        # 1. 把标准ISO时间字符串转成带时区的时间 → 时间戳A
        dt = datetime.fromisoformat(time_str)
        timestamp_a = dt.timestamp()

        # 2. 以该时间为基准，计算cron上一次执行时间 → 时间戳B
        cron_expr = settings.CMDB_INCREMENTAL_DATA_SYNC_CRONTAB
        cron = croniter.croniter(cron_expr, dt)
        last_exec_dt = cron.get_prev(datetime)
        timestamp_b = last_exec_dt.timestamp()

        # 3. 对比返回
        return timestamp_a < timestamp_b
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
