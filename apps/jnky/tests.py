import base64
import os
import django


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

from unittest import TestCase
from common.utils import Crypto


class TestTaskCase(TestCase):
    def test(self):
        text = "hello world"
        crypto = Crypto()
        cipher = crypto.encrypt(text)  # 返回密文字节
        print(cipher)  # 打印字节（可转为 hex 查看）
        plain = crypto.decrypt(cipher)  # 返回明文字符串
        print(plain)

