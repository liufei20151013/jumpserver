import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

import json
from datetime import datetime
import requests

from authentication.tests.access_key import get_auth
from orgs.models import Organization

from django.test import TestCase


class TestTaskCase(TestCase):
    def test_add_user(self):
        data = {"uid": "tianxm", "userName": "PAM测试", "jobNum": "001", "orgId": "0001", "orgName": "研发部",
                "companies": "派拉", "sex": "1", "email": "liufei@fit2cloud.com", "phone": "15911111664", "status": "1",
                "userType": "0"}  # 缺少password参数
        KeyID = "xxxxxx"
        SecretID = "xxxxxx"
        auth = get_auth(KeyID, SecretID)
        gmt_form = '%a, %d %b %Y %H:%M:%S GMT'
        now = datetime.utcnow().strftime(gmt_form)
        jms_url = "http://127.0.0.1:8080"
        url = '{}/api/v1/users/doAddUser/'.format(jms_url)
        headers = {
            'Accept': 'application/json',
            'X-JMS-ORG': Organization.DEFAULT_ID,
            'Date': now
        }
        response = requests.post(url, auth=auth, headers=headers, data=data)
        data = json.loads(response.text)
        print(data)

    def test_add_org(self):
        data = {"id": "0001", "name": "研发部2", "parentId": "-1", "parentName": "立邦PAM", "orgCode": "0001",
                "status": "1"}
        KeyID = "xxxxxx"
        SecretID = "xxxxxx"
        auth = get_auth(KeyID, SecretID)
        gmt_form = '%a, %d %b %Y %H:%M:%S GMT'
        now = datetime.utcnow().strftime(gmt_form)
        jms_url = "http://127.0.0.1:8080"
        url = '{}/api/v1/orgs/doAddOrg/'.format(jms_url)
        headers = {
            'Accept': 'application/json',
            'X-JMS-ORG': Organization.DEFAULT_ID,
            'Date': now
        }
        response = requests.post(url, auth=auth, headers=headers, data=data)
        data = json.loads(response.text)
        print(data)
