#!/usr/bin/env python
#
"""
多端点日志物理共享：内置日志同步服务。

角色由 LOG_SYNC_TARGET 是否设置决定（同一份代码按环境变量分支）：

- 推送方（端点 worker 节点）：LOG_SYNC_TARGET 非空，周期执行 rsync 把本地
  CELERY_LOG_DIR 镜像到主节点（用 temp+rename 原子替换，不使用 --inplace/--delete）。
- 汇聚方（主节点，即用户回显日志的节点）：LOG_SYNC_TARGET 为空，只做批量日志的
  后台增量聚合（把已同步到位的子任务日志逐块并入 batch 文件）。

单机部署两者均为 no-op（无 rsync 目标、活跃批量集合为空），轻量无害。
"""
import os
import signal
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS_DIR = os.path.join(BASE_DIR, 'apps')

sys.path.insert(0, APPS_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')

import django
django.setup()

import redis_lock
from django.conf import settings
from django.core.cache import cache

from common.utils import get_logger
from common.utils.connection import get_redis_client
from common.utils.endpoint_routing import (
    get_active_batch_ids, remove_active_batch, BATCH_ACTIVE_SET_KEY,
)
from ops import batch_log

logger = get_logger(__name__)

# 日志同步配置：优先 settings（config.yml 已由 settings/base.py 映射，环境变量优先于 config.yml）
def _sync_conf(name, default):
    val = getattr(settings, name, None)
    return default if val is None or val == '' else val


LOG_SYNC_TARGET = str(_sync_conf('LOG_SYNC_TARGET', '')).strip()
LOG_SYNC_RSH = str(_sync_conf('LOG_SYNC_RSH', '')).strip()
LOG_SYNC_INTERVAL = float(_sync_conf('LOG_SYNC_INTERVAL', 3))
LOG_SYNC_ENABLE_AGGREGATE = str(_sync_conf('LOG_SYNC_ENABLE_AGGREGATE', '1')) != '0'

CELERY_LOG_DIR = settings.CELERY_LOG_DIR

# batch_tasks_{batch_id} 的 TTL（与分发端 cache.set 一致）
BATCH_TASKS_TTL = 3600

_running = True


def stop(sig, frame):
    global _running
    _running = False
    logger.info('Received signal %s, stopping log sync service', sig)


def _run_rsync():
    """执行一次 rsync 镜像：本地 CELERY_LOG_DIR -> LOG_SYNC_TARGET"""
    target = LOG_SYNC_TARGET.rstrip('/') + '/'
    # 默认 temp+rename 原子替换，保证"文件尾部即 magic mark"判定可靠；
    # 不用 --inplace（会破坏原子性）、不用 --delete（会误删主节点自身日志/batch 文件）。
    cmd = [
        'rsync', '-az', '--no-owner', '--no-group',
    ]
    if LOG_SYNC_RSH:
        cmd += ['-e', LOG_SYNC_RSH]
    cmd += [CELERY_LOG_DIR.rstrip('/') + '/', target]
    try:
        logger.info('rsync logs to %s', target)
        proc = subprocess.run(cmd, check=False)
        if proc.returncode != 0:
            logger.warning('rsync to %s exited with code %s', target, proc.returncode)
    except Exception as e:
        logger.warning('rsync to %s failed: %s', target, e)


def sync_logs():
    """推送方：周期执行 rsync 把本地日志镜像到主节点"""
    if not LOG_SYNC_TARGET:
        return
    _run_rsync()


def _is_aggregator():
    """汇聚方判定：无 rsync 目标 且 未显式关闭聚合"""
    return (not LOG_SYNC_TARGET) and LOG_SYNC_ENABLE_AGGREGATE


def aggregate_batches():
    """汇聚方：后台增量聚合活跃批量任务"""
    if not _is_aggregator():
        return
    r = get_redis_client()
    batch_ids = get_active_batch_ids()
    for batch_id in batch_ids:
        try:
            _aggregate_batch(batch_id, r)
        except Exception as e:
            logger.warning('Aggregate batch %s failed: %s', batch_id, e)


def _aggregate_batch(batch_id, r):
    task_ids = cache.get(f'batch_tasks_{batch_id}')
    if not task_ids:
        # 元数据缺失/过期，移除活跃标记避免死循环
        logger.warning('Batch %s meta not found, remove from active set', batch_id)
        remove_active_batch(batch_id)
        return
    # 刷新 TTL 防长批量任务执行期间元数据过期
    cache.expire(f'batch_tasks_{batch_id}', BATCH_TASKS_TTL)

    # Redis 锁防多进程并发聚合同一批量文件
    lock = redis_lock.Lock(
        r, name=f'log-sync-aggregate-{batch_id}', expire=60, auto_renewal=True
    )
    with lock:
        _appended, done = batch_log.ensure_batch_log(batch_id, task_ids)
    if done:
        remove_active_batch(batch_id)
        cache.delete(f'batch_tasks_{batch_id}')
        logger.info('Batch %s fully aggregated, removed from active set', batch_id)
    elif not _appended:
        # 子任务尚未同步完成，静默等待下一轮
        pass


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    if LOG_SYNC_TARGET:
        logger.info('log_sync service running as pusher, target=%s', LOG_SYNC_TARGET)
    elif _is_aggregator():
        logger.info('log_sync service running as aggregator (scan %s)', BATCH_ACTIVE_SET_KEY)
    else:
        logger.info('log_sync service running as no-op (no target, aggregation disabled)')

    while _running:
        try:
            sync_logs()
            aggregate_batches()
        except Exception as e:
            logger.warning('log_sync loop error: %s', e)
        time.sleep(LOG_SYNC_INTERVAL)


if __name__ == '__main__':
    main()
