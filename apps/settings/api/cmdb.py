from rest_framework import status
from rest_framework.views import Response, APIView
from cmdb.task import sync_cmdb_full_data, sync_cmdb_incremental_data
from settings.models import Setting


class CMDBSyncFullDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_cmdb'
    }

    def post(self, request, *args, **kwargs):
        task = self._run_task()
        return Response({'task': task.id}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _run_task():
        task = sync_cmdb_full_data.delay()
        return task


class CMDBSyncIncrementalDataAPI(APIView):
    perm_model = Setting
    rbac_perms = {
        'POST': 'settings.change_cmdb'
    }

    def post(self, request, *args, **kwargs):
        task = self._run_task()
        return Response({'task': task.id}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _run_task():
        task = sync_cmdb_incremental_data.delay()
        return task
