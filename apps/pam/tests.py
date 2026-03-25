import os

import django


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

from pam.main import relate_asset_to_account
from unittest import TestCase


class TestTaskCase(TestCase):
    def test(self):
        isFullSync = False
        assets = [
            {
                "id": "6670f6c6c47dd6f044896247",
                "assetId": "",
                "name": "10.1.10.11-api01",
                "type": "db_inceptor",
                "ipv4": "10.1.10.11",
                "category": "host"
            }
        ]

        accounts = [
            {
                "id": "6614fe2549d995000de0eb2b",
                "assetId": "6670f6c6c47dd6f044896247",
                "assetAccount": "root",
                "verifyStatus": "3",
                "accountType": "0",
                "createTime": 1712651813000,
                "verifyTime": 1713576681249,
                "dept": {
                    "deptId": "661618e2d93419000c5a1d79",
                    "deptName": "test"
                }
            },{
                "id": "6614fe2549d995000de0eb27",
                "assetId": "6670f6c6c47dd6f044896247",
                "assetAccount": "appuser",
                "verifyStatus": "3",
                "accountType": "1",
                "createTime": 1712651813000,
                "verifyTime": 1713576681249,
                "dept": {
                    "deptId": "661618e2d93419000c5a1d79",
                    "deptName": "test"
                }
            }
        ]

        relate_asset_to_account(assets, accounts, isFullSync)
