import time
import json
from datetime import datetime, date

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
    relate_asset_to_account(assets, accounts, isFullSync)
    print("===== PAM 同步全部完成 =====")


def get_timestamp(hour):
    today = datetime.combine(date.today(), datetime.min.time().replace(hour=hour))
    return int(today.timestamp() * 1000)


def relate_asset_to_account(pam_assets, pam_accounts, isFullSync):
    pam_asset_dict = {}
    pam_asset_account_dict = {}

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


    # pam_account_secret_dict = {}
    privileged_accounts = ['root', 'cyuser', 'loginuser', 'wlsoper']
    url = '{PAM_SERVER}/openapi/v1/account/info/getPwd'.format(PAM_SERVER=settings.PAM_SERVER)
    orgs = Organization.objects.all()
    for org in orgs:
        set_current_org(org)

        assets = Asset.objects.filter(is_active=True)
        for asset in assets:
            print(f"Sync asset's accounts, asset: {asset.address}, org_id: {org.id}]")
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
            if 'pc_server' in comment:
                address = comment.split('-')[1].strip()
                # address = 'https://' + comment.split('-')[1].strip()
            elif any(k in comment for k in ['storage_oss', 'fc_storage', 'network_storage']):
                address = comment.split('-')[1].strip()
            key = f"{address}_{asset_category}"

            asset_id = pam_asset_dict.get(key, '')
            if not asset_id:
                print("Asset[{}-{}] not exist, asset_category:{}, skip."
                      .format(asset_id, asset.address, asset_category))
                continue

            account_arr = pam_asset_account_dict.get(asset_id, [])
            if len(account_arr) == 0:
                continue
            print("pam account_arr: {}.".format(json.dumps(account_arr)))

            for account in account_arr:
                username = account.get('assetAccount', '')
                if not username:
                    continue

                if asset_category == 'host':
                    if not org.name.__contains__(asset.comment) and username in privileged_accounts:
                        continue

                try:
                    # 多组织存在相同资产、账号，可减少接口调用查询时间  可能相同地址存在多个账号，密码被覆盖
                    # account_key = f"{str(asset.address)}_{str(username)}_{asset_category}"
                    # secret = pam_account_secret_dict.get(account_key, '')
                    # if not secret:
                    #     result = search_by_id(url, account['id'])
                    #     if result['code'] != '1000':
                    #         print("获取 PAM 上的账号密码失败, account_id:{}, asset_category:{}, code: {}, error: {}."
                    #               .format(account['id'], asset_category, result['code'], result.get('msg', '')))
                    #         continue
                    #     secret = result.get('rows', '')
                    #     pam_account_secret_dict.update({account_key: secret})

                    # 可能相同地址存在多个账号，密码被覆盖
                    result = search_by_id(url, account['id'])
                    if result['code'] != '1000':
                        print("获取 PAM 上的账号密码失败, account_id:{}, asset_category:{}, code: {}, error: {}."
                              .format(account['id'], asset_category, result['code'], result.get('msg', '')))
                        continue
                    secret = result.get('rows', '')

                    name = asset.address + "_" + username
                    privileged = True if account.get('accountType', '') == '0' else False
                    account_list = Account.objects.filter(asset=asset, username=username)
                    if not account_list.exists():
                        if asset.category == 'host' and username == 'root':
                            su_from_username = 'cyuser' if asset.platform.name in ['AIX', 'AIX-1'] else 'loginuser'
                            account = Account.objects.filter(asset=asset, username=su_from_username).first()
                            if not account:
                                su_from_name = asset.address + '_' + su_from_username
                                account = Account.objects.create(asset=asset,
                                                       name=su_from_name,
                                                       username=su_from_username,
                                                       privileged=False,
                                                       secret_type=SecretType.PASSWORD,
                                                       _secret=secret,
                                                       org_id=org.id)
                                print("Success to create account[{}] for asset[{}], asset_category:{}."
                                      .format(su_from_username, asset.address, asset_category))
                            Account.objects.create(asset=asset,
                                                   name=name,
                                                   username=username,
                                                   privileged=privileged,
                                                   secret_type=SecretType.PASSWORD,
                                                   _secret=secret,
                                                   su_from=account,
                                                   org_id=org.id)
                            print("Success to create account[{}] for asset[{}], asset_category:{}."
                                  .format(username, asset.address, asset_category))
                        else:
                            Account.objects.create(asset=asset,
                                                   name=name,
                                                   username=username,
                                                   privileged=privileged,
                                                   secret_type=SecretType.PASSWORD,
                                                   _secret=secret,
                                                   org_id=org.id)
                        print("Success to create account[{}] for asset[{}], asset_category:{}."
                              .format(username, asset.address, asset_category))
                    else:
                        if asset.category == 'host' and username == 'root':
                            su_from_username = 'cyuser' if asset.platform.name in ['AIX', 'AIX-1'] else 'loginuser'
                            account = Account.objects.filter(asset=asset, username=su_from_username).first()
                            if not account:
                                su_from_name = asset.address + '_' + su_from_username
                                account = Account.objects.create(asset=asset,
                                                                 name=su_from_name,
                                                                 username=su_from_username,
                                                                 privileged=False,
                                                                 secret_type=SecretType.PASSWORD,
                                                                 _secret=secret,
                                                                 org_id=org.id)
                                print("Success to create account[{}] for asset[{}], asset_category:{}."
                                      .format(su_from_username, asset.address, asset_category))

                            account_list.update(asset=asset,
                                                name=name,
                                                username=username,
                                                privileged=privileged,
                                                secret_type=SecretType.PASSWORD,
                                                _secret=secret,
                                                su_from=account,
                                                org_id=org.id)
                            print("Success to update account[{}] for asset[{}], asset_category:{}."
                                  .format(username, asset.address, asset_category))
                        else:
                            account_list.update(asset=asset,
                                                name=name,
                                                username=username,
                                                privileged=privileged,
                                                secret_type=SecretType.PASSWORD,
                                                _secret=secret,
                                                org_id=org.id)
                        print("Success to update account[{}] for asset[{}], asset_category:{}."
                              .format(username, asset.address, asset_category))
                except Exception as e:
                    print("Failed to save account[{}] for asset[{}], asset_category:{}, error:{}"
                          .format(username, asset.address, asset_category, e))


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

