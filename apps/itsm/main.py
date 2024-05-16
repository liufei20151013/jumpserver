import traceback
from datetime import datetime

import requests
import json

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from accounts.const import SecretStrategy, SSHKeyStrategy, AutomationTypes
from accounts.tasks import execute_account_automation_task
from common.const import Trigger
from orgs.utils import set_current_org
from perms.const import ActionChoices

from orgs.models import Organization
from accounts.models import Account, AccountTemplate, ChangeSecretAutomation, AutomationExecution, \
    AccountBackupAutomation
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
    areaStr = settings.ITSM_AREA
    if len(areaStr) == 0:
        print('未填写区域.')
        return
    env = settings.ITSM_ENVIRONMENT
    if len(env) == 0:
        print('未填写环境.')
        return

    org = Organization.objects.get(id=Organization.DEFAULT_ID)
    set_current_org(org)

    changedPwdAccounts = 0
    areaArr = str(areaStr).split(',')
    opts = ['新增', '延期', '移除', '注销']
    for area in areaArr:
        for opt in opts:
            changedPwdAccounts += data_distribution(opt, area, env, changedPwdAccounts)
    print('changedPwdAccounts: {}'.format(changedPwdAccounts))

    # 更改 自动改密后账号备份 计划
    name = '自动改密后账号备份'
    automations = AccountBackupAutomation.objects.filter(name=name)
    if automations.exists():
        automation = automations.first()
        crontab = automation.crontab
        today_of_month = datetime.now().date().day
        if automation.is_periodic and len(crontab) > 0:
            strList = crontab.split(' ')
            if strList[2] != str(today_of_month):
                # 第二天
                # 关闭自定义账号备份任务
                automation.is_periodic = False
                automation.save()
                print('Successfully changed the timed account backup plan.')

                # 删除临时的改密计划
                # changeSecretAutomations = ChangeSecretAutomation.objects.filter(name__icontains='tentative_')
                # changeSecretAutomations.delete()
                # print('Successfully changed the timed account backup plan and deleted the temporary password change plan.')

        if changedPwdAccounts > 0:
            crontab = '* 22 {} * *'.format(today_of_month)
            automation.crontab = crontab
            automation.is_periodic = True
            automation.save()
            print("Success to update account backup plan, crontab: {}".format(crontab))
    else:
        print("Account backup plan not exist! Please create an account backup plan with the name {}.".format(name))

    print('ITSM 数据处理 End.')


def data_distribution(option, area, env, changedPwdAccounts):
    result = search(option, area, env)
    if result['code'] != 0:
        print("CMDB {}数据查询失败，code: {}".format(option, result['code']))
        return

    print("CMDB 数据查询成功，total: {}, option: {}".format(result['data']['total'], option))
    data = result['data']['list']
    if option == '新增':
        changedPwdAccounts = save_or_update_asset(data, changedPwdAccounts)
    elif option == '延期':
        extend_permission(data)
    elif option == '移除':
        remove_user_asset_permission(data)
    elif option == '注销':
        update_user_state(data)
    return changedPwdAccounts


def save_or_update_asset(assets, changedPwdAccounts):
    for asset in assets:
        address = asset.get('address', '')
        instanceId = asset.get('instanceId', '')
        asset_protocol = asset.get('protocol', '')
        asset_name = asset.get('asset_name', '')
        asset_type = asset.get('asset_type', '')
        default_db = asset.get('default_db', '')
        asset_platform = asset.get('platform', '')
        assetnode_name = asset.get('assetnode_name', '')

        try:
            if len(asset_name) == 0:
                print("Asset name cannot be empty！")
                update(instanceId)
                continue

            print("Save or update asset[{}].".format(asset_name))
            if asset_platform == 'ElasticSearch':
                asset_type = 'web'
                asset_protocol = ["http/80"]
                platform = Platform.objects.filter(name='Website').first()
            elif asset_platform == 'Kingbase':
                platform = Platform.objects.filter(name='PostgreSQL').first()
                if len(asset_protocol) == 0:
                    asset_protocol = ["postgresql/5432"]  # 54321 Kingbase
                else:
                    protocols = [asset_protocol]
                    asset_protocol = []
                    for p in protocols:
                        asset_protocol.append(str(p).replace('Kingbase', 'postgresql'))
            else:
                platforms = Platform.objects.filter(name=asset_platform)
                if not platforms.exists():
                    print("Platform[{}] does not exist!".format(asset_platform))

                    # 更新 ITSM 记录状态?
                    continue
                platform = platforms.first()

                # 使用默认平台协议
                if len(asset_protocol) == 0:
                    asset_protocol = []
                    protocols = PlatformProtocol.objects.filter(platform=platform)
                    if len(protocols) > 0:
                        for p in protocols:
                            asset_protocol.append("{}/{}".format(p.name, p.port))
                else:
                    asset_protocol = [asset_protocol]
                    if platform.name.lower().__contains__('windows'):
                        asset_protocol.append("winrm/5985")

            assetList = Asset.objects.filter(name=asset_name, address=address)
            if not assetList.exists():
                try:
                    assetList = Asset.objects.filter(name=asset_name)
                    if assetList.exists():
                        print("Asset[{}] is already exist! Can't create asset.".format(asset_name))
                        update(instanceId)
                        continue

                    a = Asset.objects.create(name=asset_name,
                                             address=address,
                                             platform=platform,
                                             org_id=Organization.DEFAULT_ID)

                    if asset_type == 'host':
                        asset_model = Host(asset_ptr_id=a.id)
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()
                    elif asset_type == 'db':
                        asset_model = Database(asset_ptr_id=a.id, db_name=default_db)
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()
                    elif asset_type == 'web':
                        asset_model = Web(asset_ptr_id=a.id, autofill='no')
                        asset_model.__dict__.update(a.__dict__)
                        asset_model.save()

                    create_asset_node(assetnode_name, a)
                    relate_protocols(asset_protocol, a.id)
                    print("Success to save asset[{}].".format(asset_name))

                    changedPwdAccounts = process_permission_or_account(asset, changedPwdAccounts)
                except Exception as e:
                    print("Failed to save asset[{}], error:{}".format(asset_name, e))
                continue

            try:
                for a in assetList:
                    if asset_type == 'db' and len(default_db) > 0:
                        d = Database.objects.filter(asset_ptr_id=a.id).first()
                        if d:
                            d.db_name = default_db
                            d.save()

                    create_asset_node(assetnode_name, a)
                    relate_protocols(asset_protocol, a.id)
                print("Success to update asset[{}].".format(asset_name))

                changedPwdAccounts = process_permission_or_account(asset, changedPwdAccounts)
            except Exception as e:
                print("Failed to update asset[{}], error:{}".format(asset_name, e))
        except Exception as e:
            print("Failed to save or update asset[{}], error:{}".format(asset_name, e))
    return changedPwdAccounts


def process_permission_or_account(asset, changedPwdAccounts):
    if len(asset.get('account_username', '')) > 0:
        changedPwdAccounts = save_or_update_asset_account([asset], changedPwdAccounts)
    if len(asset.get('permission_name', '')) > 0:
        save_or_update_asset_permission([asset])
    else:
        update(asset.get('instanceId'))
    return changedPwdAccounts


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


def save_or_update_asset_account(accounts, changedPwdAccounts):
    # account_username == account_name
    for account in accounts:
        asset_name = account.get('asset_name', '')
        instanceId = account.get('instanceId', '')
        account_username = account.get('account_username', '')

        try:
            print("Save or update asset[{}]'s account[{}].".format(asset_name, account_username))
            assets = Asset.objects.filter(name=asset_name)
            if not assets.exists():
                print("Asset[{}] does not exist!".format(asset_name))
                continue
            asset = assets.first()
            platform = asset.platform.name.lower()
            asset_type = asset.platform.category

            # 如果传的是普通账号，也要把 xcscsa 或 administrator 加上
            account_usernames = []
            if asset_type == 'host':
                if platform.__contains__('windows'):
                    account_usernames.append('administrator')
                else:
                    account_usernames.append('xcscsa')
            account_usernames.append(account_username)

            for au in account_usernames:
                accountList = Account.objects.filter(asset=asset, username=au)
                if accountList.exists():
                    continue

                try:
                    # 查询账号模板
                    accountTemplates = AccountTemplate.objects.filter(username=au)
                    if not accountTemplates.exists():
                        print("Account[{}]'s template not exist! Please create an account template and retry."
                              .format(au))
                        break

                    accountTemplate = accountTemplates.first()
                    Account.objects.create(asset=asset,
                                           name=au,
                                           username=au,
                                           privileged=accountTemplate.privileged,
                                           secret_type=accountTemplate.secret_type,
                                           _secret=accountTemplate.secret,
                                           org_id=Organization.DEFAULT_ID)
                    print("Success to save asset[{}]'s account[{}].".format(asset_name, au))
                    if account_username == au:
                        update(instanceId)

                    # 主机创建新账号后立即改密
                    if asset_type == 'host':
                        name = 'tentative_{}_{}'.format(asset_name, au)
                        password_rules = '{length: 30, lowercase: true, uppercase: true, digit: true, symbol: true}'

                        automations = ChangeSecretAutomation.objects.filter(name=name)
                        automations.delete()
                        automation = ChangeSecretAutomation.objects.create(name=name,
                                                                           accounts=[au],
                                                                           is_active=True,
                                                                           is_periodic=False,
                                                                           password_rules=password_rules,
                                                                           secret='',
                                                                           secret_strategy=SecretStrategy.random,
                                                                           secret_type='password',
                                                                           ssh_key_change_strategy=SSHKeyStrategy.add)
                        automation.assets.set([asset])
                        automation.save()
                        print("Success to create a change secret plan[{}] for asset[{}]'s account[{}]."
                              .format(automation.id, asset_name, au))

                        task = execute_account_automation_task.delay(
                            pid=str(automation.pk), trigger=Trigger.manual, tp=AutomationTypes.change_secret
                        )
                        print("Success to create a change secret task[{}] for asset[{}]'s account[{}]."
                              .format(task.id, asset_name, au))

                        changedPwdAccounts += 1
                except Exception as e:
                    print("Failed to save asset[{}]'s account[{}], error:{}".format(asset_name, au, e))

            continue
        except Exception as e:
            print("Failed to save or update asset[{}]'s account[{}], error:{}".format(asset_name, account_username, e))
    return changedPwdAccounts


def save_or_update_asset_permission(permissions):
    for permission in permissions:
        username = permission.get('username', '')
        instanceId = permission.get('instanceId', '')
        asset_name = permission.get('asset_name', '')
        permission_name = permission.get('permission_name', '')
        account_username = permission.get('account_username', '')

        try:
            print("Save or update asset[{}]'s permission[{}] for user[{}].".format(asset_name, permission_name, username))
            assets = Asset.objects.filter(name=asset_name)
            if not assets.exists():
                print("Asset[{}] does not exist!".format(asset_name))
                # update(instanceId)
                continue

            users = User.objects.filter(username=username)
            if not users.exists():
                print("User[{}] does not exist!".format(username))
                # update(instanceId)
                continue

            accounts = set()
            accounts.add("@INPUT")
            if len(account_username) > 0:
                accounts.add("@SPEC")
                accounts.add(account_username)

            date_start = get_date_start(permission.get('date_start', ''))
            date_expired = get_date_expired(permission.get('date_expired', ''))
            actions = to_internal_value(permission.get('action', ["connect", "copy", "paste", "share"]))

            # 特权账号授权特殊处理
            isExistPrivilegeAccount = str(permission_name).__contains__('_xcscsa') or \
                                      str(permission_name).__contains__('_administrator') or \
                                      str(account_username).__contains__('xcscsa') or \
                                      str(account_username).__contains__('_administrator')
            if isExistPrivilegeAccount:
                permissionList = AssetPermission.objects.filter(assets=assets.first(), users=users.first(),
                                                                name=permission_name)
            else:
                permissionList = AssetPermission.objects.filter(assets=assets.first(), users=users.first()).exclude(
                    Q(name__icontains='permanent') | Q(name__icontains='xcscsa') | Q(name__icontains='administrator') |
                    Q(accounts__icontains='xcscsa') | Q(accounts__icontains='administrator')
                )

            if not permissionList.exists():
                try:
                    if len(permission_name) > 0:
                        perms = AssetPermission.objects.filter(name=permission_name)
                        if perms.exists():
                            print("AssetPermission[{}] is already exist!".format(permission_name))
                            p = perms.first()
                            p.users.add(users.first())
                            p.assets.add(assets.first())
                            for account in p.accounts:
                                accounts.add(account)
                            permissionList.update(accounts=list(accounts))
                            update(instanceId)
                            continue

                    p = AssetPermission.objects.create(name=permission_name,
                                                       accounts=list(accounts),
                                                       protocols=["all"],
                                                       actions=actions,
                                                       date_start=date_start,
                                                       date_expired=date_expired,
                                                       org_id=Organization.DEFAULT_ID)
                    p.users.add(users.first())
                    p.assets.add(assets.first())
                    print("Success to save asset[{}]'s permission[{}].".format(asset_name, permission_name))

                    update(instanceId)
                except Exception as e:
                    traceback.print_exc()
                    print("Failed to save asset[{}]'s permission[{}], error:{}".format(asset_name, permission_name, e))
                continue

            try:
                if not isExistPrivilegeAccount:
                    if len(permission_name) == 0 and len(account_username) == 0:
                        permissionList.update(date_start=date_start, date_expired=date_expired)
                    else:
                        perm = permissionList.first()
                        for account in perm.accounts:
                            accounts.add(account)
                        permissionList.update(name=permission_name,
                                              accounts=list(accounts),
                                              protocols=["all"],
                                              actions=actions,
                                              date_start=date_start,
                                              date_expired=date_expired)
                    print("Success to update asset[{}]'s permission[{}].".format(asset_name, permission_name))

                update(instanceId)

            except Exception as e:
                print("Failed to update asset[{}]'s permission[{}], error:{}".format(asset_name, permission_name, e))
        except Exception as e:
            print("Failed to save or update asset permission[{}], error:{}".format(permission_name, e))


def extend_permission(permissions):
    for permission in permissions:
        username = permission.get('username', '')
        instanceId = permission.get('instanceId', '')

        try:
            print("Extend all permissions for user[{}].".format(username))
            users = User.objects.filter(username=username)
            if not users.exists():
                print("User[{}] does not exist!".format(username))
                # update(instanceId)
                continue

            date_start = get_date_start(permission.get('date_start', ''))
            date_expired = get_date_expired(permission.get('date_expired', ''))

            # 永久授权、特权账号的授权不允许延期
            permissionList = AssetPermission.objects.filter(users=users.first()).exclude(
                Q(name__icontains='permanent') | Q(name__icontains='xcscsa') | Q(name__icontains='administrator') |
                Q(accounts__icontains='xcscsa') | Q(accounts__icontains='administrator')
            )
            if permissionList.exists():
                permissionList.update(date_start=date_start, date_expired=date_expired)
                print("Success to extend all permissions for user[{}].".format(username))

            update(instanceId)
        except Exception as e:
            print("Failed to extend all asset permission for user[{}], error:{}".format(username, e))


def remove_user_asset_permission(permissions):
    for permission in permissions:
        username = permission.get('username', '')
        asset_name = permission.get('asset_name', '')
        instanceId = permission.get('instanceId', '')

        try:
            print("Remove asset[{}]'s permission for user[{}].".format(asset_name, username))
            asset = get_object_or_none(Asset, name=asset_name)
            if not asset:
                update(instanceId)
                print("Asset[{}] does not exist!".format(asset_name))
                continue

            user = get_object_or_none(User, username=username)
            if not user:
                update(instanceId)
                print("User[{}] does not exist!".format(username))
                continue

            permissionList = AssetPermission.objects.filter(assets=asset, users=user)
            if not permissionList.exists():
                update(instanceId)
                print("Asset[{}]'s permission for user[{}] does not exist!".format(asset_name, username))
                continue

            for p in permissionList:
                # p.users.remove(user) # 移除用户
                p.assets.remove(asset)  # 移除资产
                update(instanceId)
                print("Success to remove Asset[{}]'s permission for user[{}].".format(asset_name, username))

        except Exception as e:
            print("Failed to remove Asset[{}]'s permission for user[{}], error:{}".format(asset_name, username, e))


def update_user_state(users):
    for user in users:
        username = user.get('username', '')
        instanceId = user.get('instanceId', '')

        try:
            print("Update status of user[{}].".format(username))
            userList = User.objects.filter(username=username).exclude(username='admin')
            if not userList.exists():
                print("User[{}] does not exist!".format(username))
                update(instanceId)
                continue

            userList.update(is_active=False)
            update(instanceId)
            print("Success to update the status of user[{}].".format(username))

        except Exception as e:
            print("Failed to update the status of user[{}], error:{}".format(username, e))


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


def get_date_start(start_time):
    if len(start_time) > 0:
        date_start = start_time + ' 00:00:00'
    else:
        date_start = (timezone.now() + timezone.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    return date_start


def get_date_expired(expired_time):
    if len(expired_time) > 0:
        date_expired = expired_time + ' 23:59:59'
    else:
        date_expired = (timezone.now() + timezone.timedelta(days=365 * 70, hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    return date_expired
