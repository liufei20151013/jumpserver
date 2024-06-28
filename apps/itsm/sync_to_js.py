import datetime
import json
import traceback

import requests
from django.conf import settings
from httpsig.requests_auth import HTTPSignatureAuth
from common.utils import get_logger
from orgs.models import Organization

logger = get_logger(__name__)


def sync_local_mfa_to_other_js(username, otp_secret_key):
    enabled = settings.ITSM_SYNC_JS_MFA_DATA_ENABLED
    if not enabled:
        print('当前本地用户 MFA 重置后，同步到其它 JumpServer 环境的功能未开启, 不需要处理')
        return

    # 多地址用英文分号分隔
    try:
        jms_url_arr = str(settings.ITSM_SYNC_JS_MFA_HOST).split(';')
        key_id_arr = str(settings.ITSM_SYNC_JS_MFA_AK).split(';')
        secret_id_arr = str(settings.ITSM_SYNC_JS_MFA_SK).split(';')
        print("JS url size: {}".format(len(jms_url_arr)))
        print("JS Access Key size: {}".format(len(key_id_arr)))
        print("JS Secret Key size: {}".format(len(secret_id_arr)))
    except Exception as e:
        traceback.print_exc(e)
        print('账号参数配置不规范：{}'.format(e))
        return

    for index, jms_url in enumerate(jms_url_arr):
        try:
            print("Handling data, index: {}".format(index + 1))
            print("Handling data, jms_url: {}".format(jms_url))
            KeyID = key_id_arr[index]
            SecretID = secret_id_arr[index]
            auth = get_auth(KeyID, SecretID)

            # 根据 username 查询用户
            users = get_user(jms_url, auth, username)
            if users and len(users) > 0:
                user_id = users[0].get('id', '')
            else:
                print('User[{}] does not exist.'.format(username))
                continue

            update_user_mfa(jms_url, auth, user_id, username, otp_secret_key)
        except Exception as e:
            traceback.print_exc(e)
            print('同步 MFA 的接口调用失败：{}'.format(e))
            continue


def get_user(jms_url, auth, username):
    gmt_form = '%a, %d %b %Y %H:%M:%S GMT'
    now = datetime.datetime.utcnow().strftime(gmt_form)
    url = '{}/api/v1/users/users/?username={}'.format(jms_url, username)
    headers = {
        'Accept': 'application/json',
        'X-JMS-ORG': Organization.DEFAULT_ID,
        'Date': now
    }
    response = requests.get(url, auth=auth, headers=headers, verify=False)
    data = json.loads(response.text)
    return data

def update_user_mfa(jms_url, auth, user_id, username, otp_secret_key):
    gmt_form = '%a, %d %b %Y %H:%M:%S GMT'
    now = datetime.datetime.utcnow().strftime(gmt_form)
    url = '{}/api/v1/users/users/{}/mfa/update/'.format(jms_url, user_id)
    headers = {
        'Accept': 'application/json',
        'X-JMS-ORG': Organization.DEFAULT_ID,
        'Date': now
    }
    data = {"username": username, "otp_secret_key": otp_secret_key}
    response = requests.put(url, data=data, headers=headers, auth=auth, verify=False)
    if response.status_code == 200:
        print("Success to update user[{}]'s MFA.".format(username, response.reason))
    else:
        print("Failed to update user[{}]'s MFA, error:{}.".format(username, response.reason))


def get_auth(KeyID, SecretID):
    signature_headers = ['(request-target)', 'accept', 'date']
    auth = HTTPSignatureAuth(key_id=KeyID, secret=SecretID, algorithm='hmac-sha256', headers=signature_headers)
    return auth
