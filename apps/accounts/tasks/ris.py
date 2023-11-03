import json
from datetime import datetime

from gmssl.sm4 import CryptSM4, SM4_DECRYPT
from Cryptodome.Util.Padding import unpad
from Cryptodome.Cipher import AES
from base64 import b64decode

import requests
from celery import shared_task
from django.utils.translation import gettext_lazy as _

from assets.models import Asset
from common.utils import get_logger
from orgs.models import Organization
from orgs.utils import set_current_org

from jumpserver import settings as js_settings
from django.conf import settings

logger = get_logger(__name__)


@shared_task(verbose_name=_('Sync Ris PAM secret to JumpServer'))
def sync_secret_from_ris():
    ris_config_names = [k for k in js_settings.__dict__.keys() if k.startswith('RIS_')]
    ris_configs = {name: getattr(settings, name, None) for name in ris_config_names}
    enabled = ris_configs.get("RIS_ENABLED")
    if not enabled:
        print('\033[35m>>> 当前齐治 PAM 功能未开启, 不需要同步')
        return

    failed, skipped, succeeded = 0, 0, 0
    print(f'\033[33m>>> 开始同步密钥数据到 JumpServer ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")})')
    orgs = list(Organization.objects.all())
    if len(orgs) == 0:
        return

    for org in orgs:
        set_current_org(org.id)
        assets = Asset.objects.select_related('platform')
        if len(assets) == 0:
            continue

        for asset in assets:
            print(asset.name)
            accounts = asset.accounts.all()
            if len(accounts) == 0:
                continue

            if asset.platform.lower().contains('win'):
                os = 'windows'
            else:
                os = 'Linux'

            for account in accounts:
                if account.secret_type == 'password':
                    print(account.username)
                    secret = get_asset_account_secret_from_ris(account.username, os, asset.address, ris_configs)
                    if secret != '':
                        account.secret = secret
                        account.save(update_fields=['secret'])
                        succeeded += 1
                    else:
                        failed += 1
                else:
                    skipped += 1

    total = succeeded + failed + skipped
    print(
        f'\033[33m>>> 同步完成: sync_secret_from_ris, '
        f'共计: {total}, '
        f'成功: {succeeded}, '
        f'失败: {failed}, '
        f'跳过: {skipped}'
    )
    print(f'\033[33m>>> 全部同步完成 ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")})')
    print('\033[0m')


# def get_asset_account_secret_from_ris(username, os, address, ris_configs):
#     # headers = {
#     #     'Accept': 'application/json;charset=utf-8'
#     # }
#
#     data = {
#         'objectName': username,
#         'query': 'deviceType=' + os + ';address=' + address,
#         'requestReason': 'JS 资产登录查询',
#         'appId': ris_configs.get('RIS_APP_ID'),
#         'accessKeyId': ris_configs.get('RIS_ACCESS_KEY_ID'),
#         'accessKeySecret': ris_configs.get('RIS_ACCESS_KEY_SECRET'),
#         'algorithm': 'SM4',
#         'encryptionKey': 'abcdefghijklmnop'
#     }
#     response = requests.post(ris_configs.get('RIS_AUTH_URL') + '/pam/account', json=data, verify=False)
#     # response = requests.post(ris_configs.get('RIS_AUTH_URL') + '/pam/account', headers=headers, json=data,
#     # verify=False)
#     print(json.loads(response.text))
#
#     secret = ''
#     if response.extras.errorCode == "0":
#         if response.extras.encodeResult:
#             print(f'\033[31m- 同步成功')
#             secret = decrypt('SM4', 'abcdefghijklmnop', response.objectContent)
#         else:
#             print(f'\033[32m- 同步失败，原因: 未查到该账号的密码')
#     else:
#         print(f'\033[32m- 同步失败，原因: 接口调用失败，请检查参数配置或者 PAM 平台是否可用')
#     return secret

def get_asset_account_secret_from_ris(username, os, address, ris_configs):
    data = {
        'objectName': username,
        'query': 'deviceType=' + os + ';address=' + address,
        'requestReason': 'JS 资产登录查询',
        'appId': ris_configs.get('RIS_APP_ID'),
        'accessKeyId': ris_configs.get('RIS_ACCESS_KEY_ID'),
        'accessKeySecret': ris_configs.get('RIS_ACCESS_KEY_SECRET'),
        'algorithm': 'SM4',
        'encryptionKey': 'abcdefghijklmnop'
    }
    print(ris_configs.get('RIS_AUTH_URL'))
    print(f'\033[31m- 同步成功')
    secret = decrypt('SM4', 'abcdefghijklmnop', 'bDekDKgc2ms01j2l2D1TGw\u003d\u003d')
    print(secret)
    return secret

def decrypt(crypt_type, key, data):
    key = key.encode('utf-8')
    iv = '0000000000000000'.encode('utf-8')
    data = b64decode(data.encode('utf-8'))
    if crypt_type == 'AES256':
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypt_value = unpad(cipher.decrypt(data), AES.block_size).decode('utf-8')
    else:
        crypt_sm4 = CryptSM4()
        crypt_sm4.set_key(key, SM4_DECRYPT)
        decrypt_value = crypt_sm4.crypt_cbc(iv, data).decode('utf-8')
    return decrypt_value
