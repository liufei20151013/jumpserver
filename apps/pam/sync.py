import json

from rest_framework import status
from rest_framework.response import Response

from accounts.const import SecretType
from orgs.utils import set_current_org

from orgs.models import Organization
from accounts.models import Account
from assets.models import Asset
from common.utils import get_logger

from django.conf import settings

from pam.pam_http_util import PamHttpUtil

logger = get_logger(__name__)


privileged_accounts = ['root', 'loginuser', 'cyuser', 'wlsoper']
url = '{PAM_SERVER}/openapi/v1/account/info/getPwd'.format(PAM_SERVER=settings.PAM_SERVER)

def sync_asset_accounts(js_assets):
    enabled = settings.PAM_ENABLED
    if not enabled:
        logger.info('当前 PAM 同步功能未开启, 不需要处理')
        return

    logger.info("获取 PAM 上的资产数据 Start.")
    # 只能根据资产名称过滤，无法根据IP过滤，只能查询host全部资产
    result = search_asset()
    if result['code'] != 0:
        logger.error("查询 PAM 上的资产数据失败，code: {}, error: {}".format(result['code'], result['error']))
        return
    pam_assets = result['data']['list']
    logger.info("获取 PAM 上的资产数据，total: {} 条.".format(len(pam_assets)))

    address_atid_dict = {}
    for pam_asset in pam_assets:
        pam_asset_address = pam_asset.get('ipv4', '')
        pam_asset_id = pam_asset.get('id', '')
        if not pam_asset_address or not pam_asset_id:
            continue
        key = f"{pam_asset_address}"
        address_atid_dict[key] = pam_asset_id

    for js_asset in js_assets:
        if js_asset.category == 'host':
            asset_category = 'host'
        elif js_asset.category == 'database':
            asset_category = 'db'
        elif js_asset.category == 'web':
            asset_category = 'web'
        else:
            continue

        # web地址不匹配的暂不考虑
        js_asset_address = js_asset.address
        if asset_category == 'web' and js_asset.comment.__contains__('pc_server'):
            js_asset_address = js_asset.comment.split('-')[1].strip()
            # js_asset_address = 'https://' + js_asset.comment.split('-')[1].strip()

        pam_asset_id = address_atid_dict.get(js_asset_address)
        if not pam_asset_id:
            logger.error("PAM 上不存在资产[{}]的数据.".format(js_asset.name))
            continue

        logger.info("获取 PAM 上资产[{}]的数据 Start.".format(js_asset.name))
        result = search_account(pam_asset_id)
        if result['code'] != 0:
            logger.error("查询 PAM 上资产[{}]的账号数据失败，code: {}, error: {}".format(js_asset.name, result['code'], result['error']))
            continue
        accounts = result['data']['list']
        logger.info("获取 PAM 上资产[{}]的账号数据 End，total: {} 条.".format(js_asset.name, len(accounts)))
        if not accounts:
            continue
        logger.info("pam accounts: {}.".format(json.dumps(accounts)))

        logger.info("关联 PAM 上资产[{}]的账号数据 Start.".format(js_asset.name))
        relate_asset_to_account(js_asset, accounts, asset_category)
        logger.info("关联 PAM 上资产[{}]的账号数据 End.".format(js_asset.name))
    return Response(status=status.HTTP_200_OK)


def relate_asset_to_account(asset, pam_accounts, asset_category):
    org = Organization.objects.get(id=asset.org_id)
    set_current_org(org)

    for pam_account in pam_accounts:
        username = pam_account.get('assetAccount', '')
        if not username:
            continue
        if asset_category == 'host':
            if not org.name.__contains__(asset.comment) and username in privileged_accounts:
                continue

        try:
            # 可能相同地址存在多个账号，密码被覆盖
            result = search_by_id(url, pam_account['id'])
            if result['code'] != '1000':
                print("获取 PAM 上的账号密码失败, account_id:{}, asset_category:{}, code: {}, error: {}."
                      .format(pam_account['id'], asset_category, result['code'], result.get('msg', '')))
                continue
            secret = result.get('rows', '')

            username = pam_account.get('assetAccount', '')
            if not username:
                continue
            if asset_category == 'host':
                if not org.name.__contains__(asset.comment) and username in privileged_accounts:
                    continue

            name = asset.address + "_" + username
            privileged = True if pam_account.get('accountType', '') == '0' else False
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
            logger.error("Failed to save account[{}] for asset[{}], asset_category:{}, error:{}".format(username, asset.address, asset_category, e))


def search_asset():
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

    url = '{PAM_SERVER}/openapi/v1/asset/info/list'.format(PAM_SERVER=settings.PAM_SERVER)
    logger.info("url: {}".format(url))

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        base_param["pageNum"] = current_page
        logger.info("base_param: {}".format(json.dumps(base_param)))

        response = PamHttpUtil.post_with_param(
            url=url,
            param=base_param,
            result_class=dict,
            api_key=settings.PAM_API_KEY
        )
        code = response["code"]

        if code != '1000':
            message = response["msg"]
            logger.info("Search asset failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            return result

        res = response["rows"]
        total_pages = res["total"] // limit + (1 if res["total"] % limit != 0 else 0)

        result["data"]["total"] = res["total"]
        result["data"]["list"].extend(res["list"])
        current_page += 1

    # logger.info("search asset result: {}".format(json.dumps(result)))
    return result

def search_account(pam_asset_id):
    # keyword 根据 资产IP 查询关联的账号  这里是模糊查询，需要根据资产ip和category再过滤下账号，多次调用PAM接口
    limit = 10
    base_param = {
        "pageNum": "",
        "pageSize": limit,
        "assetId": pam_asset_id
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
    logger.info("url: {}".format(url))

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        base_param["pageNum"] = current_page
        logger.info("base_param: {}".format(json.dumps(base_param)))

        response = PamHttpUtil.post_with_param(
            url=url,
            param=base_param,
            result_class=dict,
            api_key=settings.PAM_API_KEY
        )
        code = response["code"]

        if code != '1000':
            message = response["msg"]
            logger.error("Search account failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            return result

        res = response["rows"]
        total_pages = res["total"] // limit + (1 if res["total"] % limit != 0 else 0)

        result["data"]["total"] = res["total"]
        result["data"]["list"].extend(res["list"])
        current_page += 1

    # logger.info("search account result: {}".format(json.dumps(result)))
    return result

def search_by_id(url, id):
    base_param = {
        "id": id
    }
    logger.info("url: {}".format(url))
    logger.info("base_param: {}".format(json.dumps(base_param)))

    result = PamHttpUtil.post_with_param(
        url=url,
        param=base_param,
        result_class=dict,
        api_key=settings.PAM_API_KEY
    )
    # logger.info("search result: {}".format(json.dumps(result)))
    return result
