import base64

import requests
from gmssl import sm2

from common.utils import get_logger
from ..base import BaseVault

from jumpserver import settings as js_settings
from django.conf import settings

logger = get_logger(__name__)

__all__ = ['Pilla']


class Pilla(BaseVault):

    def is_active(self):
        return True, ''

    def _get(self, instance):
        secret = ''
        try:
            config_names = [k for k in js_settings.__dict__.keys() if k.startswith('VAULT_PILLA')]
            configs = {name: getattr(settings, name, None) for name in config_names}
            url = configs.get('VAULT_PILLA_AUTH_URL') + '/openapi/v1/uah/account/pwd'
            authorization = 'Bearer {}'.format(configs.get('VAULT_PILLA_TOKEN'))
            headers = {'Authorization': authorization, 'Content-Type': 'application/json'}
            data = {'id': instance.id}
            r = requests.post(url, headers=headers, json=data, verify=False)
            response = r.json()
            code = response["code"]
            if code != "200":
                message = response["msg"]
                logger.error("Search Pilla account info failed. Error: {}".format(message))
                return secret

            password = response["data"]["password"]
            private_key = base64.b64decode(configs.get('VAULT_PILLA_PRIVATE_KEY')).hex()
            sm2_cry = sm2.CryptSM2(public_key='', private_key=private_key, mode=1)
            decrypt_info = sm2_cry.decrypt(bytes.fromhex(password[2:]))
            secret = decrypt_info.decode('utf-8')
        except Exception as e:
            logger.error("Failed to call Pilla's interface. Error: {}".format(e))
        return secret

    def _create(self, instance):
        """ Ignore """
        pass

    def _update(self, instance):
        """ Ignore """
        pass

    def _delete(self, instance):
        """ Ignore """
        pass

    def _save_metadata(self, instance, metadata):
        """ Ignore """
        pass

    def _clean_db_secret(self, instance):
        """ Ignore *重要* 不能删除本地 secret """
        pass
