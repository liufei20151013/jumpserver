from ..hands import *
from .base import BaseService


__all__ = ['LogSyncService']


class LogSyncService(BaseService):
    """
    日志同步服务。

    worker 端点节点通过 rsync 把本地 CELERY_LOG_DIR 镜像到主节点，
    主节点（LOG_SYNC_TARGET 为空的节点）在该服务里执行批量日志的
    后台增量聚合。单机部署时两个循环均为轻量 no-op。
    """

    @property
    def cmd(self):
        print("\n- Start Log Sync as Periodic Service")
        cmd = [
            sys.executable, 'start_log_sync.py',
        ]
        return cmd

    @property
    def cwd(self):
        return os.path.join(BASE_DIR, 'utils')
