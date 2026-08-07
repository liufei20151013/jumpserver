import asyncio
import os

import aiofiles
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from common.db.utils import close_old_connections
from common.utils import get_logger
from orgs.mixins.ws import OrgMixin
from orgs.utils import tmp_to_org
from rbac.builtin import BuiltinRole
from .ansible.utils import get_ansible_task_log_path
from .celery.utils import get_celery_task_log_path
from .const import CELERY_LOG_MAGIC_MARK
from .models import CeleryTaskExecution

logger = get_logger(__name__)


class TaskLogWebsocket(AsyncJsonWebsocketConsumer, OrgMixin):
    disconnected = False
    user_tasks = (
        'ops.tasks.run_ops_job',
        'ops.tasks.run_ops_job_execution',
    )

    log_types = {
        'celery': get_celery_task_log_path,
        'ansible': get_ansible_task_log_path
    }

    async def connect(self):
        user = self.scope["user"]
        if user.is_authenticated:
            await self.accept()
            self.cookie = self.get_cookie()
            self.org = self.get_current_org()
        else:
            await self.close()

    def get_log_path(self, task_id, log_type):
        func = self.log_types.get(log_type)
        if func:
            return func(task_id)

    @sync_to_async
    def get_task(self, task_id):
        task = CeleryTaskExecution.objects.filter(id=task_id).first()
        # task.creator 是 foreign key, 会异步去查询的，在下面的 if task.creator 会报错, 所以这里先取出来
        if task and task.creator != ' ':
            return task
        else:
            return None

    @sync_to_async
    def get_current_user_role_ids(self, user):
        with tmp_to_org(self.org):
            org_roles = user.org_roles.all()
        system_roles = user.system_roles.all()
        roles = system_roles | org_roles
        user_role_ids = set(map(str, roles.values_list('id', flat=True)))
        return user_role_ids

    async def receive_json(self, content, **kwargs):
        task_id = content.get('task')

        # 检查是否为批量任务 batch_id（非 celery 任务 ID）
        is_batch = await self._is_batch_task(task_id)
        if not is_batch:
            task = await self.get_task(task_id)
            if not task:
                await self.send_json({'message': 'Task not found', 'task': task_id})
                return

            admin_auditor_role_ids = {
                BuiltinRole.system_admin.id,
                BuiltinRole.system_auditor.id,
                BuiltinRole.org_admin.id,
                BuiltinRole.org_auditor.id
            }
            user = self.scope['user']
            user_role_ids = await self.get_current_user_role_ids(user)
            has_admin_auditor_role = bool(admin_auditor_role_ids & user_role_ids)
            has_perms = await self.has_perms(user, ['audits.view_joblog'])
            user_can_view = task.creator == user or (task.name in self.user_tasks and has_perms)
            # (有管理员或审计员角色) 或者 (任务是用户自己创建的 或者 有查看任务日志权限), 其他情况没有权限
            if not (has_admin_auditor_role or user_can_view):
                await self.send_json({'message': 'No permission', 'task': task_id})
                return

        task_type = content.get('type', 'celery')
        log_path = self.get_log_path(task_id, task_type)
        await self.async_handle_task(task_id, log_path)

    async def async_handle_task(self, task_id, log_path):
        logger.info("Task id: {}".format(task_id))

        # 检查是否为批量任务（batch_id），如果是则自动聚合子任务日志
        is_batch = await self._is_batch_task(task_id)
        if is_batch:
            logger.info("Task {} is a batch task, aggregating sub-task logs".format(task_id))

        timeout = 0
        while not self.disconnected:
            if not os.path.exists(log_path):
                if timeout >= 60:
                    await self.send_json({'message': '\r\n', 'task': task_id})
                    await self.send_json({'message': 'Task log was not found, the directory may not be shared.',
                         'task': task_id})
                    break
                # 等待增量同步将日志推送到本节点
                await self.send_json({'message': '.', 'task': task_id})
                timeout += 0.5
                await asyncio.sleep(0.5)
            else:
                await self.send_task_log(task_id, log_path)
                break

    @sync_to_async
    def _is_batch_task(self, task_id):
        """检查 task_id 是否为批量任务的 batch_id"""
        try:
            # 写入端（endpoint_routing.py）用 Django cache.set 存储 batch_tasks_xxx，
            # 键会带上版本前缀（如 ':1:batch_tasks_xxx'）。这里必须用 cache.get 读取，
            # 直接用 get_redis_client().exists 查的是无前缀的裸键，永远查不到，
            # 导致批量任务被误判为普通 celery 任务而返回 "Task not found"。
            from django.core.cache import cache
            return bool(cache.get(f'batch_tasks_{task_id}'))
        except Exception:
            return False

    async def send_task_log(self, task_id, log_path):
        await self.send_json({'message': '\r\n'})
        try:
            logger.debug('Task log path: {}'.format(log_path))
            async with aiofiles.open(log_path, 'rb') as task_log_f:
                while not self.disconnected:
                    data = await task_log_f.read(4096)
                    if data:
                        data = data.replace(b'\n', b'\r\n')
                        await self.send_json(
                            {'message': data.decode(errors='ignore'), 'task': task_id}
                        )
                        if data.find(CELERY_LOG_MAGIC_MARK) != -1:
                            await self.send_json(
                                {'event': 'end', 'task': task_id, 'message': ''}
                            )
                            logger.debug("Task log file magic mark found")
                            break
                    await asyncio.sleep(0.2)
        except OSError as e:
            logger.warning('Task log path open failed: {}'.format(e))

    async def disconnect(self, close_code):
        self.disconnected = True
        close_old_connections()
