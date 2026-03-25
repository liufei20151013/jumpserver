from rest_framework import status
from rest_framework.views import Response, APIView

from pam.task import sync_pam_full_data, sync_pam_incremental_data
from settings.models import Setting


class PAMSyncFullDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_pam'
    }

    def post(self, request, *args, **kwargs):
        task = self._run_task()
        return Response({'task': task.id}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _run_task():
        task = sync_pam_full_data.delay()
        return task


class PAMSyncIncrementalDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_pam'
    }

    def post(self, request, *args, **kwargs):
        task = self._run_task()
        return Response({'task': task.id}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _run_task():
        task = sync_pam_incremental_data.delay()
        return task
