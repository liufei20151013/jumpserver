import datetime
import json
import requests
from django.conf import settings
from httpsig.requests_auth import HTTPSignatureAuth

from accounts.models import Account
from assets.models import Asset
from common.utils import get_logger
from orgs.models import Organization
from orgs.utils import set_current_org

logger = get_logger(__name__)


def sync_other_js_data():
    enabled = settings.ITSM_SYNC_JS_DATA_ENABLED
    if not enabled:
        print('当前同步其它 JumpServer 环境资产账号密码的功能未开启, 不需要处理')
        return

    org = Organization.objects.get(id=Organization.DEFAULT_ID)
    set_current_org(org)

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

            for acc in accountList:
                acc.secret = account.get('secret', '')
                acc.save()
            # accountList.update(_secret=account['secret'], date_updated=datetime.datetime.now())
            print("Success to update asset[{}]'s account[{}]'s secret.".format(asset.name, account['username']))


def get_accounts(jms_url, auth):
    date_form = '%Y-%m-%d %H:%M:%S'
    gmt_form = '%a, %d %b %Y %H:%M:%S GMT'
    now = datetime.datetime.now()
    start = now - datetime.timedelta(hours=23, minutes=59, seconds=59)
    date_from = start.strftime(date_form)
    date_to = now.strftime(date_form)
    url = '{}/api/v1/accounts/account-secrets/?date_from={}&date_to={}'.format(jms_url, date_from, date_to)
    headers = {
        'Accept': 'application/json',
        'X-JMS-ORG': Organization.DEFAULT_ID,
        'Date': datetime.datetime.utcnow().strftime(gmt_form)
    }

    response = requests.get(url, auth=auth, headers=headers, verify=False)
    data = json.loads(response.text)
    # print(json.loads(response.text))
    return data


def get_auth(KeyID, SecretID):
    signature_headers = ['(request-target)', 'accept', 'date']
    auth = HTTPSignatureAuth(key_id=KeyID, secret=SecretID, algorithm='hmac-sha256', headers=signature_headers)
    return auth
