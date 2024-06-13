import datetime
import json
import requests
from django.conf import settings
from httpsig.requests_auth import HTTPSignatureAuth

from accounts.models import Account
from assets.models import Asset
from common.utils import get_logger
from orgs.models import Organization

logger = get_logger(__name__)


def sync_other_js_data():
    enabled = settings.ITSM_SYNC_JS_DATA_ENABLED
    if not enabled:
        print('当前同步其它 JumpServer 环境资产账号密码的功能未开启, 不需要处理')
        return

    jms_url = settings.ITSM_SYNC_JS_HOST
    KeyID = settings.ITSM_SYNC_JS_AK
    SecretID = settings.ITSM_SYNC_JS_SK
    auth = get_auth(KeyID, SecretID)
    accounts = get_accounts(jms_url, auth)
    for account in accounts:
        asset_address = account['asset']['address']
        assets = Asset.objects.filter(address=asset_address)
        if not assets.exists():
            continue

        for asset in assets:
            accountList = Account.objects.filter(asset=asset, username=account['username'])
            if not accountList.exists():
                continue

            accountList.update(_secret=account['secret'])
            print("Success to update asset[{}]'s account[{}]'s secret.".format(asset.name, account['username']))


def get_accounts(jms_url, auth):
    gmt_form = '%a, %d %b %Y %H:%M:%S GMT'
    now = datetime.datetime.utcnow()
    start = now - datetime.timedelta(hours=23, minutes=59, seconds=59)
    date_from = start.strftime(gmt_form)
    date_to = now.strftime(gmt_form)
    url = '{}/api/v1/accounts/account-secrets/?date_from={}&date_to={}'.format(jms_url, date_from, date_to)
    headers = {
        'Accept': 'application/json',
        'X-JMS-ORG': Organization.DEFAULT_ID,
        'Date': date_to
    }

    response = requests.get(url, auth=auth, headers=headers)
    data = json.loads(response.text)
    # print(json.loads(response.text))
    return data


def get_auth(KeyID, SecretID):
    signature_headers = ['(request-target)', 'accept', 'date']
    auth = HTTPSignatureAuth(key_id=KeyID, secret=SecretID, algorithm='hmac-sha256', headers=signature_headers)
    return auth
