import time
import json
from collections import defaultdict
from datetime import datetime, date

from croniter import croniter
from django.db import transaction

from accounts.const import SecretType
from orgs.utils import set_current_org

from orgs.models import Organization
from accounts.models import Account
from assets.models import Asset
from common.utils import get_logger

from django.conf import settings

from pam.pam_http_util import PamHttpUtil

logger = get_logger(__name__)


def process_data(isFullSync):
    if not settings.PAM_ENABLED:
        print('PAM 同步功能未开启')
        return

    print("===== 开始获取 PAM 资产数据 =====")
    assets = []
    for category in ["host", "db", "web"]:
        res = search_asset(category)
        if res['code'] != 0:
            print(f"获取[{category}]资产失败: {res['error']}")
            return
        assets.extend(res['data']['list'])
        print(f"[{category}] 资产获取完成，累计：{len(assets)}")

    print("===== 开始获取 PAM 账号数据 =====")
    res = search_account()
    if res['code'] != 0:
        print(f"获取账号失败: {res['error']}")
        return
    accounts = res['data']['list']
    print(f"账号获取完成，总数：{len(accounts)}")

    print("===== 开始关联同步 =====")
    # 按组织分组：key=组织对象，value=该组织下所有待处理数据
    org_data_map = defaultdict(lambda: {
        "create": [],
        "normal_update": [],
        "su_from_update": []
    })

    relate_asset_to_account(assets, accounts, isFullSync, org_data_map)

    for org, batch in org_data_map.items():
        org_batch_run(
            org=org,
            create_objs=batch["create"],
            normal_update_objs=batch["normal_update"],
            su_from_update_objs=batch["su_from_update"]
        )
    print("===== PAM 同步全部完成 =====")

# 批量分片大小，根据业务数据量调整
BATCH_SIZE = 200

def org_batch_run(org, create_objs, normal_update_objs, su_from_update_objs):
    """
    单组织批量执行入口
    :param org: 当前操作组织
    :param create_objs: 待创建 Account 列表
    :param update_objs: 待更新 Account 列表
    """
    set_current_org(org)

    # 1. 批量创建资产账号
    if create_objs:
        start_time = time.time()
        Account.objects.bulk_create(create_objs, batch_size=BATCH_SIZE)
        end_time = time.time()
        total_seconds = end_time - start_time
        print(f"create_objs 程序总执行时间：{total_seconds:.2f} 秒")

    # 2. 批量更新普通资产账号
    base_fields = ["asset", "name", "username", "privileged", "secret_type", "_secret", "org_id"]
    if normal_update_objs:
        start_time = time.time()
        Account.objects.bulk_update(normal_update_objs,fields=base_fields, batch_size=BATCH_SIZE)
        end_time = time.time()
        total_seconds = end_time - start_time
        print(f"normal_update_objs 程序总执行时间：{total_seconds:.2f} 秒")

    # 3. 批量更新 root 资产账号
    su_from_fields = base_fields + ["su_from"]
    if su_from_update_objs:
        start_time = time.time()
        Account.objects.bulk_update(su_from_update_objs,fields=su_from_fields, batch_size=BATCH_SIZE)
        end_time = time.time()
        total_seconds = end_time - start_time
        print(f"su_from_update_objs 程序总执行时间：{total_seconds:.2f} 秒")


def get_timestamp(hour):
    today = datetime.combine(date.today(), datetime.min.time().replace(hour=hour))
    return int(today.timestamp() * 1000)


def relate_asset_to_account(pam_assets, pam_accounts, isFullSync, org_data_map):
    pam_asset_dict = {}
    pam_asset_account_dict = {}

    isSync = False
    cron_expr = settings.PAM_FULL_DATA_SYNC_CRONTAB
    hour = croniter(cron_expr, datetime.now()).get_next(datetime).hour
    today_sync_timpstamp = get_timestamp(hour)
    now_hour_timestamp = get_timestamp(datetime.now().hour)
    if now_hour_timestamp > today_sync_timpstamp and isFullSync:
        isSync = True
        isFullSync = False

    # 针对新增的机器
    # date_created = (timezone.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
    # new_assets = Asset.objects.filter(date_created__gte=date_created)
    # if new_assets.exists():
    #     isSync = False
    #     isFullSync = True

    if isFullSync:
        for asset in pam_assets:
            asset_id = asset.get('id', '')
            asset_address = asset.get('ipv4', '')
            asset_category = asset.get('category', '')
            if not asset_id or not asset_address or not asset_category:
                continue
            key = f"{str(asset_address)}_{asset_category}"
            pam_asset_dict.update({key: asset_id})

        for account in pam_accounts:
            verify_status = account.get('verifyStatus', '')
            asset_id = account.get('assetId', '')
            # 校验状态 0: 未校验(未知) 1:进行中 2:校验无效 3:校验未通过 4:校验通过
            if not verify_status or not asset_id:
                continue

            account_arr = pam_asset_account_dict.get(asset_id, [])
            account_arr.append(account)
            pam_asset_account_dict.update({asset_id: account_arr})
    else:
        if isSync:
            timestamp = today_sync_timpstamp
        else:
            # 只同步一个小时前新增的账号或者新校验的账号
            timestamp = int(time.time() * 1000) - 3600000
        for account in pam_accounts:
            verify_status = account.get('verifyStatus', '')
            asset_id = account.get('assetId', '')
            if not verify_status or not asset_id:
                continue

            save_time = account.get('verifyTime') or account.get('createTime')
            if save_time > timestamp:
                account_arr = pam_asset_account_dict.get(asset_id, [])
                account_arr.append(account)
                pam_asset_account_dict.update({asset_id: account_arr})
        if len(pam_asset_account_dict) == 0:
            return

        for asset in pam_assets:
            asset_id = asset.get('id', '')
            asset_address = asset.get('ipv4', '')
            asset_category = asset.get('category', '')
            if not asset_id or not asset_address or not asset_category:
                continue
            account_arr = pam_asset_account_dict.get(asset_id, [])
            if len(account_arr) == 0:
                continue

            key = f"{str(asset_address)}_{asset_category}"
            pam_asset_dict.update({key: asset_id})

    pam_account_secret_dict = {}
    url = '{PAM_SERVER}/openapi/v1/account/info/getPwd'.format(PAM_SERVER=settings.PAM_SERVER)
    orgs = Organization.objects.exclude(id=Organization.SYSTEM_ID)
    for org in orgs:
        set_current_org(org)

        assets = Asset.objects.all()
        for asset in assets:
            if asset.category == 'host':
                asset_category = 'host'
            elif asset.category == 'database':
                asset_category = 'db'
            elif asset.category == 'web':
                asset_category = 'web'
            else:
                continue

            address = asset.address
            comment = asset.comment
            # if 'pc_server' in comment:
            #     address = comment.split('-')[1].strip()
            # el
            if any(k in comment for k in ['storage_oss', 'fc_storage', 'network_storage']):
                address = comment.split('-')[1].strip()
            key = f"{address}_{asset_category}"

            asset_id = pam_asset_dict.get(key, '')
            if not asset_id:
                print("Asset[{}-{}] not exist, asset_category:{}, skip.".format(asset_id, asset.address, asset_category))
                continue

            account_arr = pam_asset_account_dict.get(asset_id, [])
            if len(account_arr) == 0:
                continue
            print("pam account_arr: {}.".format(json.dumps(account_arr)))

           # 查询堡垒机资产下有哪些账号
           #  js_accounts = Account.objects.filter(asset_id=asset.id)

            # pam_accounts = []
            for account in account_arr:
                username = account.get('assetAccount', '')
                if not username:
                    continue
                # if asset_category == 'host':
                #     if not org.name.__contains__(asset.comment) and username in ['root', 'loginuser', 'cyuser']:
                #         continue

                # 需要添加的账号
                # pam_accounts.append(username)

                try:
                    # 多组织存在相同资产、账号，可减少接口调用查询时间
                    account_key = f"{str(asset.address)}_{str(username)}_{asset_category}"
                    secret = pam_account_secret_dict.get(account_key, '')
                    if not secret:
                        result = search_by_id(url, account['id'])
                        if result['code'] != '1000':
                            print("获取 PAM 上的账号密码失败, account_id:{}, asset_category:{}, code: {}, error: {}."
                                  .format(account['id'], asset_category, result['code'], result.get('msg', '')))
                            continue
                        secret = result.get('rows', '')
                        pam_account_secret_dict.update({account_key: secret})

                    name = asset.address + "_" + username
                    privileged = True if account.get('accountType', '') == '0' else False
                    exist_account = Account.objects.filter(asset=asset, username=username).first()
                    if not exist_account:
                        if asset.category == 'host' and username == 'root':
                            su_from_username = 'cyuser' if asset.platform.name == 'AIX' else 'loginuser'
                            su_from_account = Account.objects.filter(asset=asset, username=su_from_username).first()
                            if not su_from_account:
                                su_from_name = asset.address + '_' + su_from_username
                                # su_from_account 需要先建，以防批量创建或更新的时候出现冲突
                                su_from_account = Account.objects.create(asset=asset,
                                                             name=su_from_name,
                                                             username=su_from_username,
                                                             privileged=False,
                                                             secret_type=SecretType.PASSWORD,
                                                             _secret=secret,
                                                             org_id=org.id)
                                print("Success to create account[{}] for asset[{}], asset_category:{}."
                                      .format(su_from_username, asset.address, asset_category))

                            new_account = Account(
                                    asset=asset,
                                    name=name,
                                    username=username,
                                    privileged=privileged,
                                    secret_type=SecretType.PASSWORD,
                                    _secret=secret,
                                    su_from=su_from_account,
                                    org_id=org.id
                                )
                            org_data_map[org]["create"].append(new_account)
                        else:
                            new_account = Account(
                                    asset=asset,
                                    name=name,
                                    username=username,
                                    privileged=privileged,
                                    secret_type=SecretType.PASSWORD,
                                    _secret=secret,
                                    org_id=org.id
                                )
                            org_data_map[org]["create"].append(new_account)
                        print("Success to create account[{}] for asset[{}], asset_category:{}."
                              .format(username, asset.address, asset_category))
                    else:
                        exist_account.asset = asset
                        exist_account.name = name
                        exist_account.username = username
                        exist_account.privileged = privileged
                        exist_account.secret_type = SecretType.PASSWORD
                        exist_account._secret = secret
                        exist_account.org_id = org.id
                        if asset.category == 'host' and username == 'root':
                            su_from_username = 'cyuser' if asset.platform.name == 'AIX' else 'loginuser'
                            su_from_account = Account.objects.filter(asset=asset, username=su_from_username).first()
                            if not su_from_account:
                                su_from_name = asset.address + '_' + su_from_username
                                # su_from_account 需要先建，以防批量创建或更新的时候出现冲突
                                su_from_account = Account.objects.create(asset=asset,
                                                             name=su_from_name,
                                                             username=su_from_username,
                                                             privileged=False,
                                                             secret_type=SecretType.PASSWORD,
                                                             _secret=secret,
                                                             org_id=org.id)

                            exist_account.su_from = su_from_account
                            org_data_map[org]["su_from_update"].append(exist_account)
                        else:
                            org_data_map[org]["normal_update"].append(exist_account)
                        print("Success to update account[{}] for asset[{}], asset_category:{}.".format(username, asset.address, asset_category))
                except Exception as e:
                    print("Failed to save account[{}] for asset[{}], asset_category:{}, error:{}".format(username, asset.address, asset_category, e))

            # 清理多余的账号  如果接口调用失败，存在误删账号的情况！！！建议手动删除多余账号。
            # print("js_accounts size: {}, pam_accounts size: {}.".format(len(js_accounts), len(pam_accounts)))
            # if len(js_accounts) > len(pam_accounts):
            #     print("Remove extra accounts of asset[{}], asset_category:{}.".format(asset.address, asset_category))
            #     for ja in js_accounts:
            #         if ja.username not in pam_accounts:
            #             try:
            #                 print("Remove account[{}].".format(ja.username))
            #                 Account.objects.get(id=ja.id).delete()
            #                 print("Success to remove account[{}].".format(ja.username))
            #             except:
            #                 print("Failed to remove account[{}].".format(ja.username))
            #                 continue


def search_asset(category):
    limit = 10000
    base_param = {
        "pageNum": "",
        "pageSize": limit,
        "category": category
    }

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "data": {
            "total": 0,
            "list": []
        }
    }

    url = '{PAM_SERVER}/openapi/v1/asset/info/list'.format(PAM_SERVER=settings.PAM_SERVER)
    print("url: {}".format(url))

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        base_param["pageNum"] = current_page
        print("base_param: {}".format(json.dumps(base_param)))

        response = PamHttpUtil.post_with_param(
            url=url,
            param=base_param,
            result_class=dict,
            api_key=settings.PAM_API_KEY
        )
        code = response["code"]

        if code != '1000':
            message = response["msg"]
            print("Search asset failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            return result

        res = response["rows"]
        total_pages = res["total"] // limit + (1 if res["total"] % limit != 0 else 0)

        result["data"]["total"] = res["total"]
        result["data"]["list"].extend(res["list"])
        current_page += 1

    # print("search asset result: {}".format(json.dumps(result)))
    return result

def search_account():
    limit = 10000
    base_param = {
        "pageNum": "",
        "pageSize": limit
    }

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "data": {
            "total": 0,
            "list": []
        }
    }

    url = '{PAM_SERVER}/openapi/v1/account/info/list'.format(PAM_SERVER=settings.PAM_SERVER)
    print("url: {}".format(url))

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        base_param["pageNum"] = current_page
        print("base_param: {}".format(json.dumps(base_param)))

        response = PamHttpUtil.post_with_param(
            url=url,
            param=base_param,
            result_class=dict,
            api_key=settings.PAM_API_KEY
        )
        code = response["code"]

        if code != '1000':
            message = response["msg"]
            print("Search account failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            return result

        res = response["rows"]
        total_pages = res["total"] // limit + (1 if res["total"] % limit != 0 else 0)

        result["data"]["total"] = res["total"]
        result["data"]["list"].extend(res["list"])
        current_page += 1

    # print("search account result: {}".format(json.dumps(result)))
    return result

def search_by_id(url, id):
    base_param = {
        "id": id
    }
    print("url: {}".format(url))
    print("base_param: {}".format(json.dumps(base_param)))

    result = PamHttpUtil.post_with_param(
        url=url,
        param=base_param,
        result_class=dict,
        api_key=settings.PAM_API_KEY
    )
    # print("search result: {}".format(json.dumps(result)))
    return result
