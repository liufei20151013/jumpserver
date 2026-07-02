import time

from celery import shared_task
from django.utils.translation import gettext_lazy as _

from cmdb.utils import acquire_sync_lock, release_incr_lock, release_sync_lock, full_sync_is_running, acquire_incr_lock, \
    incr_sync_is_running
from common.utils import get_logger
from cmdb.main import process_data
from ops.celery.decorator import after_app_ready_start
from ops.celery.utils import disable_celery_periodic_task, create_or_update_celery_periodic_tasks
from django.conf import settings

logger = get_logger(__name__)

@shared_task(verbose_name=_('Sync cmdb full data to JumpServer'))
def sync_cmdb_full_data():
    # 尝试抢占全量锁
    if not acquire_sync_lock():
        logger.warning("全量同步已在运行，本次任务退出")
        return

    # 释放正在运行的增量任务，执行全量任务（业务优先全量）
    if incr_sync_is_running():
        logger.info("CMDB全量同步，强优先级执行")
        release_incr_lock()

    try:
        process_data(True)
        logger.info("CMDB全量同步完成")
    except Exception as e:
        logger.error(f"全量同步异常: {e}", exc_info=True)
    finally:
        release_sync_lock()


@shared_task(verbose_name=_('Registration periodic sync cmdb full data task'))
@after_app_ready_start
def sync_cmdb_full_data_periodic():
    if not settings.CMDB_ENABLED:
        return
    task_name = 'sync_cmdb_full_data_periodic'

    try:
        disable_celery_periodic_task(task_name)
    except Exception as e:
        print('sync_cmdb_full_data_periodic does not exist')

    crontab = settings.CMDB_FULL_DATA_SYNC_CRONTAB
    if crontab:
        tasks = {
            task_name: {
                'task': sync_cmdb_full_data.name,
                'interval': None,
                'crontab': crontab,
                'enabled': True,
            }
        }
        create_or_update_celery_periodic_tasks(tasks)


@shared_task(verbose_name=_('Sync cmdb incremental data to JumpServer'))
def sync_cmdb_incremental_data():
    # 检测全量同步是否在运行
    time.sleep(10)
    if full_sync_is_running():
        logger.warning("存在CMDB全量同步任务，终止本次增量同步")
        return

    # 尝试获取增量自身锁，防止并发增量
    if not acquire_incr_lock():
        logger.warning("已有增量同步正在运行，跳过")
        return

    try:
        logger.info("开始执行增量数据同步")
        process_data(False)
    except Exception as e:
        logger.error(f"增量同步异常: {e}", exc_info=True)
    finally:
        release_incr_lock()


@shared_task(verbose_name=_('Registration periodic sync cmdb incremental data task'))
@after_app_ready_start
def sync_cmdb_incremental_data_periodic():
    if not settings.CMDB_ENABLED:
        return
    task_name = 'sync_cmdb_incremental_data_periodic'

    try:
        disable_celery_periodic_task(task_name)
    except Exception as e:
        print('sync_cmdb_incremental_data_periodic does not exist')

    crontab = settings.CMDB_INCREMENTAL_DATA_SYNC_CRONTAB
    if crontab:
        tasks = {
            task_name: {
                'task': sync_cmdb_incremental_data.name,
                'interval': None,
                'crontab': crontab,
                'enabled': True,
            }
        }
        create_or_update_celery_periodic_tasks(tasks)
