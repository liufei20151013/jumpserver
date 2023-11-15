from django.test import TestCase

from assets.models import Asset
from orgs.models import Organization
from orgs.utils import set_current_org

class TestTaskCase(TestCase):
    def test_get_all_assets(self):
        orgs = list(Organization.objects.all())
        if len(orgs) == 0:
            return

        for org in orgs:
            set_current_org(org.id)
            assets = Asset.objects.select_related('platform')
            if len(assets) == 0:
                continue

            for asset in assets:
                print(asset.address)
                print(asset.platform)
                accounts = asset.accounts.all()
                if len(accounts) == 0:
                    continue

                for account in accounts:
                    if account.secret_type == "password":
                        print(account.username)
                        account.secret = "root2222"
                        account.save(update_fields=['secret'])



