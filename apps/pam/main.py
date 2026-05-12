import time
import json
from datetime import datetime, date, timedelta

from croniter import croniter
from django.utils import timezone

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
    enabled = settings.PAM_ENABLED
    if not enabled:
        print('当前 PAM 同步功能未开启, 不需要处理')
        return

    print("获取 PAM 上的资产数据 Start.")
    category_arr = ["host", "db", "web"]
    assets = []
    for category in category_arr:
        result = search_asset(category)
        if result['code'] != 0:
            print("查询 PAM 上的[{}]资产数据失败，code: {}, error: {}".format(category, result['code'], result['error']))
            return
        assets.extend(result['data']['list'])
    print("获取 PAM 上的[{}]资产数据 End，total: {} 条.".format(category, len(assets)))

    print("获取 PAM 上的数据 Start.")
    result = search_account()
    if result['code'] != 0:
        print("查询 PAM 上的资产数据失败，code: {}, error: {}".format(result['code'], result['error']))
        return
    accounts = result['data']['list']
    print("获取 PAM 上的账号数据 End，total: {} 条.".format(len(accounts)))

    print("关联 PAM 上的账号数据 Start.")
    relate_asset_to_account(assets, accounts, isFullSync)
    print("关联 PAM 上的账号数据 End.")


def get_timestamp(hour):
    today = datetime.combine(date.today(), datetime.min.time().replace(hour=hour))
    timestamp_ms = int(today.timestamp() * 1000)
    return timestamp_ms


def relate_asset_to_account(assets, accounts, isFullSync):
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
        for asset in assets:
            asset_id = asset.get('id', '')
            asset_address = asset.get('ipv4', '')
            asset_category = asset.get('category', '')
            if not asset_id or not asset_address or not asset_category:
                continue
            key = f"{str(asset_address)}_{asset_category}"
            pam_asset_dict.update({key: asset_id})

        for account in accounts:
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
        for account in accounts:
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

        for asset in assets:
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

    privileged_accounts = ['root', 'loginuser', 'cyuser']

    url = '{PAM_SERVER}/openapi/v1/account/info/getPwd'.format(PAM_SERVER=settings.PAM_SERVER)
    orgs = Organization.objects.exclude(id=Organization.SYSTEM_ID)
    for org in orgs:
        set_current_org(org)

        assets = Asset.objects.exclude(name__istartswith='jms_')
        for asset in assets:
            if asset.category == 'host':
                asset_category = 'host'
            elif asset.category == 'database':
                asset_category = 'db'
            elif asset.category == 'web':
                asset_category = 'web'
            else:
                continue

            key = f"{str(asset.address)}_{asset_category}"
            if asset.comment.__contains__('pc_server'):
                address = 'https://' + asset.comment.split('-')[1].strip()
                key = f"{str(address)}_{asset_category}"
            asset_id = pam_asset_dict.get(key, '')
            if not asset_id:
                print("Asset[{}-{}] not exist, asset_category:{}, skip.".format(asset_id, asset.address, asset_category))
                continue

            account_arr = pam_asset_account_dict.get(asset_id, [])
            if len(account_arr) == 0:
                continue

           # 查询堡垒机资产下有哪些账号
           #  js_accounts = Account.objects.filter(asset_id=asset.id)

            # pam_accounts = []
            for account in account_arr:
                username = account.get('assetAccount', '')
                if not username:
                    continue
                if asset_category == 'host':
                    if not org.name.__contains__(asset.comment) and username in privileged_accounts:
                        continue

                # 需要添加的账号
                # pam_accounts.append(username)

                try:
                    result = search_by_id(url, account['id'])
                    if result['code'] != '1000':
                        print("获取 PAM 上的账号密码失败, account_id:{}, asset_category:{}, code: {}, error: {}.".format(account['id'], asset_category, result['code'], result.get('msg', '')))
                        continue
                    secret = result.get('rows', '')

                    name = asset.address + "_" + username
                    privileged = True if account.get('accountType', '') == '0' else False
                    account_list = Account.objects.filter(asset=asset, username=username)
                    if not account_list.exists():
                        if asset.category == 'host' and username == 'root':
                            if asset.platform.name == 'AIX':
                                su_from_username = 'cyuser'
                            else:
                                su_from_username = 'loginuser'
                            accounts = Account.objects.filter(asset=asset, username=su_from_username)
                            if not accounts.exists():
                                su_from_name = asset.address + '_' + su_from_username
                                acc = Account.objects.create(asset=asset,
                                                       name=su_from_name,
                                                       username=su_from_username,
                                                       privileged=False,
                                                       secret_type=SecretType.PASSWORD,
                                                       _secret=secret,
                                                       org_id=org.id)
                                print("Success to create account[{}] for asset[{}], asset_category:{}.".format(su_from_username, asset.address, asset_category))
                            else:
                                acc = accounts.first()
                            Account.objects.create(asset=asset,
                                                   name=name,
                                                   username=username,
                                                   privileged=privileged,
                                                   secret_type=SecretType.PASSWORD,
                                                   _secret=secret,
                                                   su_from=acc,
                                                   org_id=org.id)
                        else:
                            Account.objects.create(asset=asset,
                                                   name=name,
                                                   username=username,
                                                   privileged=privileged,
                                                   secret_type=SecretType.PASSWORD,
                                                   _secret=secret,
                                                   org_id=org.id)
                        print("Success to create account[{}] for asset[{}], asset_category:{}.".format(username, asset.address, asset_category))
                    else:
                        if asset.category == 'host' and username == 'root':
                            if asset.platform.name == 'AIX':
                                su_from_username = 'cyuser'
                            else:
                                su_from_username = 'loginuser'
                            accounts = Account.objects.filter(asset=asset, username=su_from_username)
                            if accounts.exists():
                                account_list.update(asset=asset,
                                                    name=name,
                                                    username=username,
                                                    privileged=privileged,
                                                    secret_type=SecretType.PASSWORD,
                                                    _secret=secret,
                                                    su_from=accounts.first(),
                                                    org_id=org.id)
                        else:
                            account_list.update(asset=asset,
                                                name=name,
                                                username=username,
                                                privileged=privileged,
                                                secret_type=SecretType.PASSWORD,
                                                _secret=secret,
                                                org_id=org.id)
                        print("Success to update account[{}] for asset[{}], asset_category:{}.".format(username, asset.address, asset_category))
                except Exception as e:
                    print("Failed to save account[{}] for asset[{}], asset_category:{}, error:{}".format(username, asset.address, asset_category, e))

            # 清理多余的账号
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
