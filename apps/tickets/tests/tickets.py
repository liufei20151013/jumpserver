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
    def test_apply_ticket(self):
        data = {"requestId": "PIM202408300005", "approveResult": "0", "opinion": "同意", "approver": "admin"}
        # data = {"requestId": "PIM202408300003", "approveResult": "1", "opinion": "规划不合理，请重新设计。", "approver": "admin"}
        KeyID = "xxxxxx"
        SecretID = "xxxxxx"
        auth = get_auth(KeyID, SecretID)
        gmt_form = '%a, %d %b %Y %H:%M:%S GMT'
        now = datetime.utcnow().strftime(gmt_form)
        jms_url = "http://127.0.0.1:8080"
        url = '{}/api/v1/tickets/approve/'.format(jms_url)
        headers = {
            'Accept': 'application/json',
            'X-JMS-ORG': Organization.DEFAULT_ID,
            'Date': now
        }
        response = requests.post(url, auth=auth, headers=headers, data=data)
        data = json.loads(response.text)
        print(data)
