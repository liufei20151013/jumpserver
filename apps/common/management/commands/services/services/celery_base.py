from .base import BaseService
from ..hands import *
from common.utils.endpoint_routing import is_master_node


class CeleryBaseService(BaseService):

    def __init__(self, queue, **kwargs):
        super().__init__(**kwargs)
        self.queue = queue
        self.num = CELERY_WORKER_COUNT

    @property
    def cmd(self):
        print('\n- Start Celery as Distributed Task Queue: {}'.format(self.queue.capitalize()))
        os.environ.setdefault('PYTHONPATH', settings.APPS_DIR)
        os.environ.setdefault('LC_ALL', 'C.UTF-8')
        os.environ.setdefault('LANG', 'C.UTF-8')
        os.environ.setdefault('PYTHONOPTIMIZE', '1')

        if os.getuid() == 0:
            os.environ.setdefault('C_FORCE_ROOT', '1')
        server_hostname = os.environ.get("SERVER_HOSTNAME")
        if not server_hostname:
            server_hostname = '%h'

        # 主节点（集控节点）额外监听 email 队列，统一接收各节点的邮件发送任务
        queues = self.queue
        if is_master_node():
            queues = '{},{}'.format(queues, settings.EMAIL_QUEUE)

        cmd = [
            'celery',
            '-A', 'ops',
            'worker',
            '-P', 'threads',
            '-l', 'INFO',
            '-c', str(self.num),
            '-Q', queues,
            '--heartbeat-interval', '10',
            '-n', f'{self.queue}@{server_hostname}',
            '--without-mingle',
        ]
        return cmd

    @property
    def cwd(self):
        return APPS_DIR
