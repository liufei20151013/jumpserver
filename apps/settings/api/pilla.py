from rest_framework.views import APIView
from settings.models import Setting


class PillaSyncDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_pilla'
    }
