import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
django.setup()

from unittest import TestCase
from dlt.tasks.main import process_data

class TestTaskCase(TestCase):
    def test_dlt(self):
        process_data(False)
