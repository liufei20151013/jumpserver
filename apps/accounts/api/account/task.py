from django.db.models import Q
from rest_framework.generics import CreateAPIView

from accounts import serializers
from accounts.models import Account
from accounts.permissions import AccountTaskActionPermission
from accounts.tasks import (
    remove_accounts_task, verify_accounts_connectivity_task, push_accounts_to_assets_task
)
from authentication.permissions import UserConfirmation, ConfirmType

__all__ = [
    'AccountsTaskCreateAPI',
]


class AccountsTaskCreateAPI(CreateAPIView):
    serializer_class = serializers.AccountTaskSerializer
    permission_classes = (AccountTaskActionPermission,)

    def get_permissions(self):
        act = self.request.data.get('action')
        if act == 'remove':
            self.permission_classes = [
                AccountTaskActionPermission,
                UserConfirmation.require(ConfirmType.PASSWORD)
            ]
        return super().get_permissions()

    @staticmethod
    def get_account_ids(data, action):
        account_type = 'gather_accounts' if action == 'remove' else 'accounts'
        accounts = data.get(account_type, [])
        account_ids = [str(a.id) for a in accounts]

        if action == 'remove':
            return account_ids

        assets = data.get('assets', [])
        asset_ids = [str(a.id) for a in assets]
        ids = Account.objects.filter(
            Q(id__in=account_ids) | Q(asset_id__in=asset_ids)
        ).distinct().values_list('id', flat=True)
        return [str(_id) for _id in ids]

    def perform_create(self, serializer):
        data = serializer.validated_data
        action = data['action']
        ids = self.get_account_ids(data, action)

        if action == 'push':
            task = push_accounts_to_assets_task.delay(ids, data.get('params'))
        elif action == 'remove':
            task = remove_accounts_task.delay(ids)
        elif action == 'verify':
            # 【端点路由】账号按所属资产端点拆分，投递各端点队列就近执行（对齐 asset.py test_account）
            from common.utils.endpoint_routing import dispatch_task_to_endpoints_for_accounts
            task = dispatch_task_to_endpoints_for_accounts(
                verify_accounts_connectivity_task, ids
            )
        else:
            raise ValueError(f"Invalid action: {action}")

        self._set_task_to_serializer_data(serializer, task)
        return task

    def _set_task_to_serializer_data(self, serializer, task):
        data = getattr(serializer, '_data', {})
        if isinstance(task, list):
            if len(task) == 1:
                data["task"] = task[0].id
            elif len(task) > 1:
                # 多端点批量任务：检查是否有 batch_id 用于日志聚合
                batch_id = self._get_batch_id_for_tasks(task)
                if batch_id:
                    data["task"] = batch_id  # 前端用 batch_id 订阅聚合日志
                else:
                    data["task"] = task[0].id  # 回退到第一个任务 ID
                data["tasks"] = [t.id for t in task]  # 所有子任务 ID
        elif task:
            data["task"] = task.id
        setattr(serializer, '_data', data)

    @staticmethod
    def _get_batch_id_for_tasks(tasks):
        """从 Redis 获取批量任务的 batch_id"""
        try:
            from django.core.cache import cache
            for t in tasks:
                batch_id = cache.get(f'task_batch_{t.id}')
                if batch_id:
                    return batch_id
        except Exception:
            pass
        return None
