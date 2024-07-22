from rest_framework import status
from rest_framework.views import Response, APIView
from itsm.task import sync_itsm_data
from settings.models import Setting


class ITSMSyncDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_itsm'
    }

    def post(self, request, *args, **kwargs):
        task = self._run_task()
        return Response({'task': task.id}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _run_task():
        task = sync_itsm_data.delay()
        return task
