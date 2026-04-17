from rest_framework import status
from rest_framework.views import Response, APIView

from dlt.tasks.task import sync_dlt_accounts_full_data, sync_dlt_accounts_incremental_data
from settings.models import Setting


class DltSyncFullDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_dlt'
    }

    def post(self, request, *args, **kwargs):
        task = self._run_task()
        return Response({'task': task.id}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _run_task():
        task = sync_dlt_accounts_full_data.delay()
        return task


class DltSyncIncrementalDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_dlt'
    }

    def post(self, request, *args, **kwargs):
        task = self._run_task()
        return Response({'task': task.id}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _run_task():
        task = sync_dlt_accounts_incremental_data.delay()
        return task
