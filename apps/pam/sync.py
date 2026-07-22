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


def process_data(js_asset):
    enabled = settings.PAM_ENABLED
    if not enabled:
        logger.info('当前 PAM 同步功能未开启, 不需要处理')
        return

    if js_asset.category == 'host':
        asset_category = 'host'
    elif js_asset.category == 'database':
        asset_category = 'db'
    elif js_asset.category == 'web':
        asset_category = 'web'
    else:
        return

    logger.info("获取 PAM 上的资产数据 Start.")
    js_asset_address = js_asset.address
    if asset_category == 'web' and js_asset.comment.__contains__('pc_server'):
        js_asset_address = js_asset.comment.split('-')[1].strip()
        # js_asset_address = 'https://' + js_asset.comment.split('-')[1].strip()

    # 只能根据资产名称过滤，无法根据IP过滤，只能查询host全部资产
    result = search_asset(asset_category)
    if result['code'] != 0:
        logger.error("查询 PAM 上的资产数据失败，code: {}, error: {}".format(asset_category, result['code'], result['error']))
        return
    pam_assets = result['data']['list']
    logger.info("获取 PAM 上的[{}]资产数据 End，total: {} 条.".format(asset_category, len(pam_assets)))

    pam_asset_id = ''
    for pam_asset in pam_assets:
        pam_asset_address = pam_asset.get('ipv4', '')
        # web地址不匹配的暂不考虑
        if pam_asset_address == js_asset_address:
            pam_asset_id = pam_asset.get('id', '')
            break

    if not pam_asset_id:
        logger.error("PAM 上不存在资产[{}]的数据.".format(js_asset.name))
        return

    logger.info("获取 PAM 上资产[{}]的数据 Start.".format(js_asset.name))
    result = search_account(pam_asset_id)
    if result['code'] != 0:
        logger.error("查询 PAM 上资产[{}]的账号数据失败，code: {}, error: {}".format(js_asset.name, result['code'], result['error']))
        return
    accounts = result['data']['list']
    logger.info("获取 PAM 上资产[{}]的账号数据 End，total: {} 条.".format(js_asset.name, len(accounts)))
    if not accounts:
        return
    logger.info("pam accounts: {}.".format(json.dumps(accounts)))

    logger.info("关联 PAM 上资产[{}]的账号数据 Start.".format(js_asset.name))
    relate_asset_to_account(js_asset, accounts, asset_category)
    logger.info("关联 PAM 上资产[{}]的账号数据 End.".format(js_asset.name))
    return Response(status=status.HTTP_200_OK)


def relate_asset_to_account(js_asset, pam_accounts, asset_category):
    pam_account_secret_dict = {}
    privileged_accounts = ['root', 'loginuser', 'cyuser', 'wlsoper']
    url = '{PAM_SERVER}/openapi/v1/account/info/getPwd'.format(PAM_SERVER=settings.PAM_SERVER)

    orgs = Organization.objects.all()
    for org in orgs:
        set_current_org(org)

        assets = Asset.objects.filter(name=js_asset.name)
        for asset in assets:
            for pam_account in pam_accounts:
                username = pam_account.get('assetAccount', '')
                if not username:
                    continue
                if asset_category == 'host':
                    if not org.name.__contains__(asset.comment) and username in privileged_accounts:
                        continue

                try:
                    # 多组织存在相同资产、账号，可减少接口调用查询时间
                    account_key = f"{str(asset.address)}_{str(username)}_{asset_category}"
                    secret = pam_account_secret_dict.get(account_key, '')
                    if not secret:
                        result = search_by_id(url, pam_account['id'])
                        if result['code'] != '1000':
                            logger.error("获取 PAM 上的账号密码失败, account_id:{}, asset_category:{}, code: {}, error: {}."
                                  .format(pam_account['id'], asset_category, result['code'], result.get('msg', '')))
                            continue
                        secret = result.get('rows', '')
                        pam_account_secret_dict.update({account_key: secret})

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
                        if asset_category == 'host' and username == 'root':
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
                                logger.info("Success to create account[{}] for asset[{}], asset_category:{}.".format(su_from_username, asset.address, asset_category))
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
                        logger.info("Success to create account[{}] for asset[{}], asset_category:{}.".format(username, asset.address, asset_category))
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
                        logger.info("Success to update account[{}] for asset[{}], asset_category:{}.".format(username, asset.address, asset_category))
                except Exception as e:
                    logger.error("Failed to save account[{}] for asset[{}], asset_category:{}, error:{}".format(username, asset.address, asset_category, e))


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
