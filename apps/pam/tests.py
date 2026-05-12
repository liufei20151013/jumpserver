import os

import django


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

from unittest import TestCase
from django.utils import timezone
import requests
import json
from croniter import croniter
from datetime import datetime

from assets.models import Asset
from jumpserver import settings
from pam.main import get_timestamp
from pam.sync import relate_asset_to_account

class TestTaskCase(TestCase):
    def test(self):
        cron_expr = '0 3 * * *'
        hour = croniter(cron_expr, datetime.now()).get_next(datetime).hour
        today_sync_timpstamp = get_timestamp(hour)
        print(today_sync_timpstamp)

        # 接口地址
        # url = "http://127.0.0.1:8080/core/auth/oauth2/callback/dlt/account"
        #
        # # 你要求的请求体（完整复制）
        # payload = {
        #     "requestId": "20250924095022765tzfyanuq",
        #     "appId": "100453",
        #     "appKey": "b092ca09-a7aa-49d4-8b32-245cc02c172d",
        #     "actionType": "Add",
        #     "accountList": [
        #         {
        #             "uid": "361570",
        #             "accountId": "361570",
        #             "accountCode": "",
        #             "encryptPassword": "FDF5398EC6F2A79E8692A3A6E3C2CF13073988267A7BF0CCFCD7D6CC6C0E8F05",
        #             "email": "weien@tpl.cntaiping.com",
        #             "status": "1",
        #             "validTime": "",
        #             "org": "W42I5YMTH8F245UIT19V",
        #             "orgName": "产品市场部",
        #             "orgFullName": "/0000000000/1000000000/1001/1002/W42I5YMTH8F245UIT19V",
        #             "tpId": "weien@tpl.cntaiping.com",
        #             "primaryAccount": "",
        #             "idCardNumber": "610*********38X",
        #             "employeeType": "1",
        #             "companyId": "1002",
        #             "companyName": "",
        #             "hrId": "16361897755679178752",
        #             "level": "",
        #             "personType": "0",
        #             "startTime": "2022-04-26",
        #             "appCustomAttrs": {}
        #         }
        #     ]
        # }
        #
        # # 请求头（必须是 JSON 格式）
        # headers = {
        #     "Content-Type": "application/json"
        # }
        #
        # response = requests.post(url, data=json.dumps(payload), headers=headers)
        # print("状态码:", response.status_code)
        # print("返回结果:", response.text)

        # isFullSync = False
        # assets = [
        #     {
        #         "id": "6670f6c6c47dd6f044896247",
        #         "assetId": "",
        #         "name": "10.1.10.11-api01",
        #         "type": "db_inceptor",
        #         "ipv4": "10.1.10.11",
        #         "category": "host"
        #     }
        # ]
        #
        # accounts = [
        #     {
        #         "id": "6614fe2549d995000de0eb2b",
        #         "assetId": "6670f6c6c47dd6f044896247",
        #         "assetAccount": "root",
        #         "verifyStatus": "4",
        #         "accountType": "0",
        #         "createTime": 1776651813000,
        #         "verifyTime": None,
        #         "dept": {
        #             "deptId": "661618e2d93419000c5a1d79",
        #             "deptName": "test"
        #         }
        #     },{
        #         "id": "6614fe2549d995000de0eb27",
        #         "assetId": "6670f6c6c47dd6f044896247",
        #         "assetAccount": "appuser",
        #         "verifyStatus": "4",
        #         "accountType": "1",
        #         "createTime": 1776651813000,
        #         "verifyTime": None,
        #         "dept": {
        #             "deptId": "661618e2d93419000c5a1d79",
        #             "deptName": "test"
        #         }
        #     }
        # ]
        #
        # relate_asset_to_account(assets, accounts, isFullSync)

    def test2(self):
        js_asset = Asset.objects.get(id='c499f81d-9cbb-4b91-9a23-fa2773b9d34d')
        pam_accounts = [
            {'id': '1', 'assetAccount': 'root', 'accountType': '0'},
            {'id': '2', 'assetAccount': 'appuser', 'accountType': '0'}
        ]
        asset_category = 'host'
        relate_asset_to_account(js_asset, pam_accounts, asset_category)
