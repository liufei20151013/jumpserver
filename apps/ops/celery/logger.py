import os
import socket
import threading

import requests
from logging import StreamHandler
from threading import get_ident

from celery import current_task
from celery.signals import task_prerun, task_postrun
from django.conf import settings
from kombu import Connection, Exchange, Queue, Producer
from kombu.mixins import ConsumerMixin

from .utils import get_celery_task_log_path
from ..const import CELERY_LOG_MAGIC_MARK

routing_key = 'celery_log'
celery_log_exchange = Exchange('celery_log_exchange', type='direct')
celery_log_queue = [Queue('celery_log', celery_log_exchange, routing_key=routing_key)]


def _get_local_names():
    # 仅用本容器/主机唯一的主机名判定"同一文件系统"。
    # 不能包含 SERVER_HOSTNAME：容器化部署下所有容器通常共享同一个值
    # （如物理机 hostname），用它判断会导致本机判定误判为 True，
    # worker 跳过 HTTP 推送，而 WebSocket 所在容器（不同文件系统）读不到日志。
    names = {socket.gethostname()}
    try:
        names.add(socket.getfqdn())
    except Exception:
        pass
    return {n for n in names if n}


def _get_local_ips():
    ips = {'127.0.0.1'}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(info[4][0])
    except (socket.gaierror, OSError):
        pass
    return ips


def _is_same_node(name):
    """判断给定的节点名（或可解析地址）是否指向本机"""
    if not name:
        return False
    if name in _get_local_names():
        return True
    try:
        local_ips = _get_local_ips()
        for info in socket.getaddrinfo(name, None):
            if info[4][0] in local_ips:
                return True
    except (socket.gaierror, OSError):
        pass
    return False


class CeleryLoggerConsumer(ConsumerMixin):
    def __init__(self):
        self.connection = Connection(settings.CELERY_LOG_BROKER_URL)

    def get_consumers(self, Consumer, channel):
        return [Consumer(queues=celery_log_queue,
                         accept=['pickle', 'json'],
                         callbacks=[self.process_task])
                ]

    def handle_task_start(self, task_id, message):
        pass

    def handle_task_end(self, task_id, message):
        pass

    def handle_task_log(self, task_id, msg, message):
        pass

    def process_task(self, body, message):
        action = body.get('action')
        task_id = body.get('task_id')
        msg = body.get('msg')
        if action == CeleryLoggerProducer.ACTION_TASK_LOG:
            self.handle_task_log(task_id, msg, message)
        elif action == CeleryLoggerProducer.ACTION_TASK_START:
            self.handle_task_start(task_id, message)
        elif action == CeleryLoggerProducer.ACTION_TASK_END:
            self.handle_task_end(task_id, message)


class CeleryLoggerProducer:
    ACTION_TASK_START, ACTION_TASK_LOG, ACTION_TASK_END = range(3)

    def __init__(self):
        self.connection = Connection(settings.CELERY_LOG_BROKER_URL)

    @property
    def producer(self):
        return Producer(self.connection)

    def publish(self, payload):
        self.producer.publish(
            payload, serializer='json', exchange=celery_log_exchange,
            declare=[celery_log_exchange], routing_key=routing_key
        )

    def log(self, task_id, msg):
        payload = {'task_id': task_id, 'msg': msg, 'action': self.ACTION_TASK_LOG}
        return self.publish(payload)

    def read(self):
        pass

    def flush(self):
        pass

    def task_end(self, task_id):
        payload = {'task_id': task_id, 'action': self.ACTION_TASK_END}
        return self.publish(payload)

    def task_start(self, task_id):
        payload = {'task_id': task_id, 'action': self.ACTION_TASK_START}
        return self.publish(payload)


class CeleryTaskLoggerHandler(StreamHandler):
    terminator = '\r\n'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        task_prerun.connect(self.on_task_start)
        task_postrun.connect(self.on_start_end)

    @staticmethod
    def get_current_task_id():
        if not current_task:
            return
        task_id = current_task.request.root_id
        return task_id

    def on_task_start(self, sender, task_id, **kwargs):
        return self.handle_task_start(task_id)

    def on_start_end(self, sender, task_id, **kwargs):
        return self.handle_task_end(task_id)

    def after_task_publish(self, sender, body, **kwargs):
        pass

    def emit(self, record):
        task_id = self.get_current_task_id()
        if not task_id:
            return
        try:
            self.write_task_log(task_id, record)
            self.flush()
        except Exception:
            self.handleError(record)

    def write_task_log(self, task_id, msg):
        pass

    def handle_task_start(self, task_id):
        pass

    def handle_task_end(self, task_id):
        pass


class CeleryThreadingLoggerHandler(CeleryTaskLoggerHandler):
    @staticmethod
    def get_current_thread_id():
        return str(get_ident())

    def emit(self, record):
        thread_id = self.get_current_thread_id()
        try:
            self.write_thread_task_log(thread_id, record)
            self.flush()
        except ValueError:
            self.handleError(record)

    def write_thread_task_log(self, thread_id, msg):
        pass

    def handle_task_start(self, task_id):
        pass

    def handle_task_end(self, task_id):
        pass

    def handleError(self, record) -> None:
        pass


class CeleryTaskMQLoggerHandler(CeleryTaskLoggerHandler):
    def __init__(self):
        self.producer = CeleryLoggerProducer()
        super().__init__(stream=None)

    def write_task_log(self, task_id, record):
        msg = self.format(record)
        self.producer.log(task_id, msg)

    def flush(self):
        self.producer.flush()


class CeleryTaskFileHandler(CeleryTaskLoggerHandler):
    def __init__(self, *args, **kwargs):
        self.f = None
        super().__init__(*args, **kwargs)

    def emit(self, record):
        msg = self.format(record)
        if not self.f or self.f.closed:
            return
        self.f.write(msg)
        self.f.write(self.terminator)
        self.flush()

    def flush(self):
        self.f and self.f.flush()

    def handle_task_start(self, task_id):
        log_path = get_celery_task_log_path(task_id)
        self.f = open(log_path, 'a')

    def handle_task_end(self, task_id):
        self.f and self.f.close()


class CeleryThreadTaskFileHandler(CeleryThreadingLoggerHandler):
    def __init__(self, *args, **kwargs):
        self.thread_id_fd_mapper = {}
        self.task_id_thread_id_mapper = {}
        # 增量同步（HTTP）相关状态
        self._sync_lock = threading.Lock()
        self._sync_buffers = {}  # task_id -> {'lines': [], 'batch_id':..., 'local':..., 'done':...}
        self._flush_locks = {}   # task_id -> Lock（保证同一任务的多次推送有序）
        self._task_mode = {}     # task_id -> 'http' | None
        self._task_owner = {}    # task_id -> owner 主机名 or None
        self._task_batch = {}    # task_id -> batch_id or None
        self._task_local = {}    # task_id -> bool（本机执行，文件已在主节点本地）
        self._sync_thread = None
        self._sync_stop = threading.Event()
        super().__init__(*args, **kwargs)
        self._start_sync_thread()

    # ---------------- 增量同步：任务状态判定（每任务只读一次缓存） ----------------

    @staticmethod
    def _read_owner(task_id):
        try:
            from django.core.cache import cache
            return cache.get(f'task_log_owner_{task_id}')
        except Exception:
            return None

    @staticmethod
    def _read_batch_id(task_id):
        try:
            from django.core.cache import cache
            return cache.get(f'task_batch_{task_id}')
        except Exception:
            return None

    @staticmethod
    def _is_http_sync_task(task_id):
        try:
            from django.core.cache import cache
            return bool(cache.get(f'task_log_http_sync_{task_id}'))
        except Exception:
            return False

    @staticmethod
    def _compute_local(owner):
        if not owner:
            return False
        return _is_same_node(owner)

    # ---------------- 增量同步：攒批与推送 ----------------

    def _start_sync_thread(self):
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._sync_thread = threading.Thread(
            target=self._sync_loop, daemon=True, name='celery-log-sync'
        )
        self._sync_thread.start()

    def _sync_loop(self):
        while not self._sync_stop.is_set():
            try:
                self._flush_all_buffers()
            except Exception:
                pass
            self._sync_stop.wait(1.0)

    def _deliver_log(self, task_id, msg):
        """
        分发一行日志：
        - 增量同步任务（连通性测试）：攒批推送到主节点；本机执行且非批量时无需推送
        - 其余任务：仅写本地文件，不做跨节点同步
        """
        if self._task_mode.get(task_id) != 'http':
            return
        local = self._task_local.get(task_id, False)
        batch_id = self._task_batch.get(task_id)
        if local and not batch_id:
            return
        self._buffer_log_line(task_id, msg, batch_id, local)

    def _buffer_log_line(self, task_id, msg, batch_id, local):
        with self._sync_lock:
            item = self._sync_buffers.setdefault(
                task_id, {'lines': [], 'batch_id': batch_id, 'local': local, 'done': False}
            )
            item['lines'].append(msg)

    def _get_flush_lock(self, task_id):
        with self._sync_lock:
            lock = self._flush_locks.get(task_id)
            if lock is None:
                lock = threading.Lock()
                self._flush_locks[task_id] = lock
            return lock

    def _flush_all_buffers(self):
        with self._sync_lock:
            buffers = self._sync_buffers
            self._sync_buffers = {}
        for task_id, item in buffers.items():
            try:
                self._flush_item(task_id, item)
            except Exception:
                self._requeue_failed(task_id, item)

    def _flush_item(self, task_id, item):
        """按任务串行推送，避免同一任务的多次推送乱序；失败重新排队重试"""
        lock = self._get_flush_lock(task_id)
        with lock:
            lines = item.get('lines') or []
            done = item.get('done', False)
            if not lines and not done:
                return
            try:
                ok = self._http_push(
                    task_id, lines, done,
                    item.get('local', False), item.get('batch_id')
                )
            except Exception:
                ok = False
            if not ok:
                self._requeue_failed(task_id, item)

    def _http_push(self, task_id, lines, done, local, batch_id):
        # 推送目标优先级：
        # 1. TASK_LOG_SYNC_HOST：仅用于日志同步的独立配置。
        #    多节点/端点部署下 CORE_HOST 常指向本节点 core（如 http://core:8080），
        #    而日志需要推到"主节点（WebSocket 所在节点）"，可单独设置该变量，
        #    避免改动 CORE_HOST 影响 koko 等其他组件。
        # 2. CORE_HOST：组件回连核心节点的地址（原逻辑）。
        # 3. SITE_URL：用户访问地址兜底。
        target = (
            os.environ.get('TASK_LOG_SYNC_HOST')
            or os.environ.get('CORE_HOST')
            or settings.SITE_URL
        )
        if not target:
            return False
        url = target.rstrip('/') + '/api/v1/ops/task-logs/sync/'
        payload = {
            'task_id': task_id,
            'lines': lines,
            'done': done,
            'local': local,
            'batch_id': batch_id,
        }
        headers = {'X-JMS-LOG-TOKEN': settings.BOOTSTRAP_TOKEN}
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        return resp.ok

    def _requeue_failed(self, task_id, item):
        """推送失败：把片段放回缓冲头部，下一轮重试，保持顺序；超限丢弃最旧行"""
        max_lines = 5000
        with self._sync_lock:
            current = self._sync_buffers.get(task_id)
            if current is None:
                self._sync_buffers[task_id] = {
                    'lines': list(item.get('lines') or []),
                    'batch_id': item.get('batch_id'),
                    'local': item.get('local', False),
                    'done': item.get('done', False),
                }
            else:
                current['lines'] = (item.get('lines') or []) + current['lines']
                if item.get('done'):
                    current['done'] = True
                if len(current['lines']) > max_lines:
                    current['lines'] = current['lines'][-max_lines:]

    def _finalize_task(self, task_id):
        """任务结束：冲刷剩余缓冲并标记完成（仅增量同步任务）"""
        if self._task_mode.get(task_id) != 'http':
            return
        with self._sync_lock:
            item = self._sync_buffers.pop(task_id, None)
        if item is None:
            item = {
                'lines': [], 'done': True,
                'batch_id': self._task_batch.get(task_id),
                'local': self._task_local.get(task_id, False),
            }
        else:
            item['done'] = True
        # 本机执行且非批量：文件已在主节点本地，无需推送
        if item.get('local') and not item.get('batch_id'):
            return
        try:
            self._flush_item(task_id, item)
        except Exception:
            self._requeue_failed(task_id, item)

    def write_thread_task_log(self, thread_id, record):
        f = self.thread_id_fd_mapper.get(thread_id, None)
        if not f:
            raise ValueError('Not found thread task file')
        msg = self.format(record)
        f.write(msg.encode())
        f.write(self.terminator.encode())
        f.flush()

        # 分发日志：增量同步任务走 HTTP 推送，其余仅写本地文件
        task_id = self.get_current_task_id()
        if task_id:
            self._deliver_log(task_id, msg)

    def flush(self):
        for f in self.thread_id_fd_mapper.values():
            f.flush()

    def handle_task_start(self, task_id):
        log_path = get_celery_task_log_path(task_id)
        thread_id = self.get_current_thread_id()
        self.task_id_thread_id_mapper[task_id] = thread_id
        f = open(log_path, 'ab')
        self.thread_id_fd_mapper[thread_id] = f

        # 增量同步状态初始化（每个任务只读一次缓存，避免逐行查 Redis）
        self._task_owner[task_id] = self._read_owner(task_id)
        self._task_batch[task_id] = self._read_batch_id(task_id)
        self._task_local[task_id] = self._compute_local(self._task_owner[task_id])
        self._task_mode[task_id] = 'http' if self._is_http_sync_task(task_id) else None
        self._sync_buffers.pop(task_id, None)

    def handle_task_end(self, task_id):
        ident_id = self.task_id_thread_id_mapper.get(task_id, '')
        f = self.thread_id_fd_mapper.pop(ident_id, None)
        if f and not f.closed:
            f.write(CELERY_LOG_MAGIC_MARK)
            f.close()
        self.task_id_thread_id_mapper.pop(task_id, None)

        # 冲刷剩余缓冲并标记完成（HTTP 增量同步）
        self._finalize_task(task_id)

        # 清理任务级状态
        self._task_owner.pop(task_id, None)
        self._task_batch.pop(task_id, None)
        self._task_local.pop(task_id, None)
        self._task_mode.pop(task_id, None)
        with self._sync_lock:
            self._flush_locks.pop(task_id, None)
