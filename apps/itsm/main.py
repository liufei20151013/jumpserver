import traceback
import requests
import json
from django.utils import timezone
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from assets.utils import check_node_assets_amount
from orgs.utils import set_current_org
from perms.const import ActionChoices

from orgs.models import Organization
from accounts.models import Account
from assets.models import Asset, Platform, Database, Web, Node, Protocol, Host, PlatformProtocol
from common.utils import get_logger, get_object_or_none
from perms.models import AssetPermission
from users.models import User

from django.conf import settings

logger = get_logger(__name__)


def process_data():
    enabled = settings.ITSM_ENABLED
    if not enabled:
        print('当前 ITSM 功能未开启, 不需要处理')
        return

    print('ITSM 数据处理 Start.')
    org = Organization.objects.get(id=Organization.DEFAULT_ID)
    set_current_org(org)

    areaStr = settings.ITSM_AREA
    if len(areaStr) == 0:
        print('未填写区域.')
        return
    env = settings.ITSM_ENVIRONMENT
    if len(env) == 0:
        print('未填写环境.')
        return

    areaArr = str(areaStr).split(',')
    for area in areaArr:
        data_distribution('新增', area, env)
        data_distribution('延期', area, env)
        data_distribution('移除', area, env)
        data_distribution('注销', area, env)

    print('ITSM 数据处理 End.')


def data_distribution(option, area, env):
    result = search(option, area, env)
    if result['code'] != 0:
        print("CMDB {}数据查询失败，code: {}".format(option, result['code']))
        return

    print("CMDB 数据查询成功，total: {}, option: {}".format(result['data']['total'], option))
    data = result['data']['list']
    if option == '新增':
        save_or_update_asset(data)
        check_node_assets_amount()
    elif option == '延期':
        extend_permission(data)
    elif option == '移除':
        remove_user_asset_permission(data)
    elif option == '注销':
        update_user_state(data)


def save_or_update_asset(assets):
    for asset in assets:
        try:
            print("Save or update asset[{}].".format(asset.get('asset_name', '')))
            if asset.get('platform', '') == 'ElasticSearch':
                asset['asset_type'] = 'web'
                asset['protocol'] = ["http/80"]
                platform = Platform.objects.filter(name='Website').first()
            elif asset.get('platform', '') == 'Kingbase':
                platform = Platform.objects.filter(name='PostgreSQL').first()
                if len(asset.get('protocol', '')) == 0:
                    asset['protocol'] = ["postgresql/5432"]  # 54321 Kingbase
                else:
                    protocols = [asset['protocol']]
                    asset['protocol'] = []
                    for p in protocols:
                        asset['protocol'].append(str(p).replace('Kingbase', 'postgresql'))
            else:
                platforms = Platform.objects.filter(name=asset['platform'])
                if not platforms.exists():
                    print("Platform[{}] does not exist!".format(asset.get('platform', '')))

                    # 更新 ITSM 记录状态?
                    continue
                platform = platforms.first()

                # 使用默认平台协议
                if len(asset.get('protocol', '')) == 0:
                    asset['protocol'] = []
                    protocols = PlatformProtocol.objects.filter(platform=platform)
                    if len(protocols) > 0:
                        for p in protocols:
                            asset['protocol'].append("{}/{}".format(p.name, p.port))
                else:
                    asset['protocol'] = [asset['protocol']]

            assetList = Asset.objects.filter(name=asset['asset_name'], address=asset['address'])
            if not assetList.exists():
                try:
                    assetList = Asset.objects.filter(name=asset['asset_name'])
                    if assetList.exists():
                        print("Asset[{}] is already exist! Can't create asset.".format(asset.get('asset_name', '')))
                        update(asset['instanceId'])
                        continue

                    a = Asset.objects.create(name=asset.get('asset_name', None),
                                             address=asset.get('address', None),
                                             platform=platform,
                                             org_id=Organization.DEFAULT_ID)

                    if asset['asset_type'] == 'host':
                        asset_model = Host(asset_ptr_id=a.id)
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()
                    elif asset['asset_type'] == 'db':
                        asset_model = Database(asset_ptr_id=a.id, db_name=asset.get('default_db', ''))
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()
                    elif asset['asset_type'] == 'web':
                        asset_model = Web(asset_ptr_id=a.id, autofill='no')
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()

                    create_asset_node(asset['assetnode_name'], a)
                    relate_protocols(asset.get('protocol', ''), a.id)
                    print("Success to save asset[{}].".format(asset.get('asset_name', '')))

                    process_permission_or_account(asset)

                except Exception as e:
                    print("Failed to save asset[{}], error:{}".format(asset.get('asset_name', ''), e))
                continue

            try:
                for a in assetList:
                    if asset['asset_type'] == 'db' and len(asset['default_db']) > 0:
                        d = Database.objects.filter(asset_ptr_id=a.id).first()
                        if d:
                            d.db_name = asset['default_db']
                            d.save()

                    create_asset_node(asset['assetnode_name'], a)
                    relate_protocols(asset['protocol'], a.id)
                print("Success to update asset[{}].".format(asset.get('asset_name', '')))

                process_permission_or_account(asset)

            except Exception as e:
                print("Failed to update asset[{}], error:{}".format(asset.get('asset_name', ''), e))
        except Exception as e:
            print("Failed to save or update asset[{}], error:{}".format(asset.get('asset_name', ''), e))


def process_permission_or_account(asset):
    if len(asset.get('account_username', '')) > 0:
        save_or_update_asset_account([asset])
    if len(asset.get('permission_name', '')) > 0:
        save_or_update_asset_permission([asset])
    else:
        update(asset['instanceId'])


def relate_protocols(string, asset_id):
    try:
        if len(string) > 0:
            for protocol in string:
                arr = str(protocol).lower().split("/")
                protocols = Protocol.objects.filter(name=arr[0], port=arr[1], asset_id=asset_id)
                if not protocols.exists():
                    Protocol.objects.create(name=arr[0], port=arr[1], asset_id=asset_id)
    except Exception as e:
        print("Relate asset[{}]'s protocols error:{}".format(asset_id, e))


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


def save_or_update_asset_account(accounts):
    # account_username == asset_name
    for account in accounts:
        try:
            print("Save or update asset[{}]'s account[{}]."
                  .format(account.get('asset_name', ''), account.get('account_username', '')))
            asset = get_object_or_none(Asset, name=account['asset_name'])
            if not asset:
                print("Asset[{}] does not exist!".format(account.get('asset_name', '')))
                continue

            accountList = Account.objects.filter(asset=asset, username=account['account_username'])
            if not accountList.exists():
                try:
                    Account.objects.create(asset=asset,
                                           name=account.get('account_username', None),
                                           username=account.get('account_username', None),
                                           privileged=account.get('is_privileged', False),
                                           secret_type=account.get('secret_type', 'password'),
                                           _secret=account.get('secret', None),
                                           org_id=Organization.DEFAULT_ID)
                    print("Success to save asset[{}]'s account[{}]."
                          .format(account.get('asset_name', ''), account.get('account_username', '')))

                    update(account['instanceId'])
                except Exception as e:
                    print("Failed to save asset[{}]'s account[{}], error:{}"
                          .format(account.get('asset_name', ''), account.get('account_username', ''), e))
                continue

            try:
                accountList.update(asset=asset,
                                   name=account.get('account_username', None),
                                   username=account.get('account_username', None),
                                   privileged=account.get('is_privileged', False),
                                   secret_type=account.get('secret_type', 'password'),
                                   _secret=account.get('secret', None),
                                   org_id=Organization.DEFAULT_ID)
                print("Success to update asset[{}]'s account[{}]."
                      .format(account.get('asset_name', ''), account.get('account_username', '')))
                update(account['instanceId'])

            except Exception as e:
                print("Failed to update asset[{}]'s account[{}], error:{}"
                      .format(account.get('asset_name', ''), account.get('account_username', ''), e))
        except Exception as e:
            print("Failed to save or update asset account[{}], error:{}".format(account.get('account_username', ''), e))


def save_or_update_asset_permission(permissions):
    for permission in permissions:
        try:
            print("Save or update asset[{}]'s permission[{}] for user[{}]."
                  .format(permission.get('asset_name', ''), permission.get('permission_name', ''),
                          permission.get('username', '')))
            assets = Asset.objects.filter(name=permission['asset_name'])
            if not assets.exists():
                print("Asset[{}] does not exist!".format(permission.get('asset_name', '')))
                # update(permission['instanceId'])
                continue

            users = User.objects.filter(username=permission['username'])
            if not users.exists():
                print("User[{}] does not exist!".format(permission.get('username', '')))
                # update(permission['instanceId'])
                continue

            actions = to_internal_value(permission.get('action', ["connect", "upload", "download", "delete", "copy",
                                                                  "paste", "share"]))

            try:
                date_start = permission.get('date_start') + ' 00:00:00' if len(permission.get('date_start')) > 0 \
                    else (timezone.now() + timezone.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                date_start = (timezone.now() + timezone.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
            try:
                date_expired = permission.get('date_expired') + ' 23:59:59' if len(permission.get('date_expired')) > 0 \
                    else (timezone.now() + timezone.timedelta(days=365 * 70, hours=8)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                date_expired = (timezone.now() + timezone.timedelta(days=365 * 70, hours=8)).strftime("%Y-%m-%d %H:%M:%S")

            accounts = set()
            accounts.add("@INPUT")
            if len(permission.get('account_username', '')) > 0:
                accounts.add(permission.get('account_username', ''))

            permissionList = AssetPermission.objects.filter(assets=assets.first(), users=users.first())
            if not permissionList.exists():
                try:
                    if len(permission.get('permission_name', '')) > 0:
                        perms = AssetPermission.objects.filter(name=permission['permission_name'])
                        if perms.exists():
                            print("AssetPermission[{}] is already exist!".format(permission.get('permission_name', '')))
                            p = perms.first()
                            p.users.add(users.first())
                            p.assets.add(assets.first())
                            for account in p.accounts:
                                accounts.add(account)
                            permissionList.update(accounts=list(accounts))
                            update(permission['instanceId'])
                            continue

                    p = AssetPermission.objects.create(name=permission.get('permission_name', ''),
                                                       accounts=list(accounts),
                                                       protocols=["all"],
                                                       actions=actions,
                                                       date_start=date_start,
                                                       date_expired=date_expired,
                                                       org_id=Organization.DEFAULT_ID)
                    p.users.add(users.first())
                    p.assets.add(assets.first())
                    print("Success to save asset[{}]'s permission[{}]."
                          .format(permission.get('asset_name', ''), permission.get('permission_name', '')))

                    update(permission['instanceId'])
                except Exception as e:
                    traceback.print_exc()
                    print("Failed to save asset[{}]'s permission[{}], error:{}"
                          .format(permission.get('asset_name', ''), permission.get('permission_name', ''), e))
                continue

            try:
                if len(permission.get('permission_name', '')) == 0 or len(permission.get('account_username', '')) == 0:
                    permissionList.update(date_start=date_start, date_expired=date_expired)
                else:
                    perm = permissionList.first()
                    for account in perm.accounts:
                        accounts.add(account)
                    permissionList.update(name=permission.get('permission_name', ''),
                                          accounts=list(accounts),
                                          protocols=["all"],
                                          actions=actions,
                                          date_start=date_start,
                                          date_expired=date_expired)
                print("Success to update asset[{}]'s permission[{}]."
                      .format(permission.get('asset_name', ''), permission.get('permission_name', '')))

                update(permission['instanceId'])

            except Exception as e:
                print("Failed to update asset[{}]'s permission[{}], error:{}"
                      .format(permission.get('asset_name', ''), permission.get('permission_name', ''), e))
        except Exception as e:
            print("Failed to save or update asset permission[{}], error:{}"
                  .format(permission.get('permission_name', ''), e))


def extend_permission(permissions):
    for permission in permissions:
        try:
            print("Extend all permissions for user[{}].".format(permission.get('username', '')))

            users = User.objects.filter(username=permission['username'])
            if not users.exists():
                print("User[{}] does not exist!".format(permission.get('username', '')))
                # update(permission['instanceId'])
                continue

            try:
                date_start = permission.get('date_start') + ' 00:00:00' if len(permission.get('date_start')) > 0 \
                    else (timezone.now() + timezone.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                date_start = (timezone.now() + timezone.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
            try:
                date_expired = permission.get('date_expired') + ' 23:59:59' if len(permission.get('date_expired')) > 0 \
                    else (timezone.now() + timezone.timedelta(days=365 * 70, hours=8)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                date_expired = (timezone.now() + timezone.timedelta(days=365 * 70, hours=8)).strftime("%Y-%m-%d %H:%M:%S")

            permissionList = AssetPermission.objects.filter(users=users.first()).exclude(name__icontains="permanent")
            if permissionList.exists():
                permissionList.update(date_start=date_start, date_expired=date_expired)
                print("Success to extend all permissions for user[{}].".format(permission.get('username', '')))

            update(permission['instanceId'])
        except Exception as e:
            print("Failed to extend all asset permission for user[{}], error:{}"
                  .format(permission.get('username', ''), e))


def remove_user_asset_permission(permissions):
    for permission in permissions:
        print("Remove asset[{}] permission for user[{}]."
              .format(permission.get('asset_name', ''), permission.get('username', '')))
        try:
            asset = get_object_or_none(Asset, name=permission['asset_name'])
            if not asset:
                update(permission['instanceId'])
                print("Asset[{}] does not exist!".format(permission.get('asset_name', '')))
                continue

            user = get_object_or_none(User, username=permission['username'])
            if not user:
                update(permission['instanceId'])
                print("User[{}] does not exist!".format(permission.get('username', '')))
                continue

            permissionList = AssetPermission.objects.filter(assets=asset, users=user)
            if not permissionList.exists():
                update(permission['instanceId'])
                print("Asset[{}] permission for user[{}] does not exist!"
                      .format(permission.get('asset_name', ''), permission.get('username', '')))
                continue

            for p in permissionList:
                # p.users.remove(user)
                p.assets.remove(asset)  # 移除资产
                update(permission['instanceId'])
                print("Success to remove Asset[{}] permission for user[{}]."
                      .format(permission.get('asset_name', ''), permission.get('username', '')))

        except Exception as e:
            print("Failed to remove Asset[{}] permission for user[{}], error:{}"
                  .format(permission.get('asset_name', ''), permission.get('username', ''), e))


def update_user_state(users):
    for user in users:
        print("Update status of user[{}].".format(user.get('username', '')))
        try:
            userList = User.objects.filter(username=user['username']).exclude(username='admin')
            if not userList.exists():
                print("User[{}] does not exist!".format(user['username']))
                update(user['instanceId'])
                continue

            userList.update(is_active=False)
            update(user['instanceId'])
            print("Success to update the status of user[{}].".format(user.get('username', '')))

        except Exception as e:
            print("Failed to update the status of user[{}], error:{}".format(user.get('username', ''), e))


def to_internal_value(data):
    if not isinstance(data, list):
        raise serializers.ValidationError(_("Invalid data type, should be list"))
    value = 0
    if not data:
        return value
    if isinstance(data[0], dict):
        data = [d["value"] for d in data]
    # 所有的
    if "all" in data:
        for c in ActionChoices:
            value |= c.value
        return value

    name_value_map = {c.name: c.value for c in ActionChoices}
    for name in data:
        if name not in name_value_map:
            raise serializers.ValidationError(_("Invalid choice: {}").format(name))
        value |= name_value_map[name]
    return value


def search(option, area, env):
    CMDB_HEADERS = {"org": settings.ITSM_ORG, "user": settings.ITSM_USER, "host": settings.ITSM_HOST}
    url = "{CMDB_SERVER}/object/{objectId}/instance/_search" \
        .format(CMDB_SERVER=settings.ITSM_SERVER, objectId=settings.ITSM_OBJECT_ID)
    data = {"query": {"handle_tag": "false", "op_type": option, "area": area, "env": env}}
    print("url: {}".format(url))
    print("data: {}".format(json.dumps(data)))

    result = {
        "code": 0,
        "error": "",
        "message": "",
        "data": {
            "page": 1,
            "page_size": data.get("pageSize", 1000),
            "total": 0,
            "list": []
        }
    }

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        data["page"] = current_page

        r = requests.post(url, headers=CMDB_HEADERS, json=data, timeout=10)
        response = r.json()
        code = response["code"]

        if code != 0:
            message = response["message"]
            print("Search request failed. Error: {}".format(message))
            result["code"] = code
            result["error"] = message
            return result

        res = response["data"]
        total_pages = res["total"] // res["page_size"] + (1 if res["total"] % res["page_size"] != 0 else 0)

        result["data"]["total"] = res["total"]
        result["data"]["list"].extend(res["list"])
        current_page += 1

    print("search_RES: {}".format(json.dumps(result)))
    return result


def update(instanceId):
    CMDB_HEADERS = {"org": settings.ITSM_ORG, "user": settings.ITSM_USER, "host": settings.ITSM_HOST}
    url = "{CMDB_SERVER}/object/instance/{objectId}/{instanceId}" \
        .format(CMDB_SERVER=settings.ITSM_SERVER, objectId=settings.ITSM_OBJECT_ID, instanceId=instanceId, timeout=10)
    data = {"handle_tag": "true"}
    print("[update] url:{}".format(url))
    r = requests.put(url, headers=CMDB_HEADERS, json=data, timeout=10)
    return r.json()
