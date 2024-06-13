from celery import shared_task
from django.utils.translation import gettext_lazy as _

from common.utils import get_logger
from itsm.main import process_data
from itsm.sync_from_js import sync_other_js_data
from ops.celery.decorator import after_app_ready_start
from ops.celery.utils import create_or_update_celery_periodic_tasks
from django.conf import settings

logger = get_logger(__name__)


@shared_task(verbose_name=_('Sync itsm data to JumpServer'))
def sync_itsm_data():
    process_data()


@shared_task(verbose_name=_('Registration periodic sync itsm data task'))
@after_app_ready_start
def sync_itsm_data_periodic():
    if not settings.ITSM_ENABLED:
        return

    task_name = 'sync_itsm_data_periodic'
    crontab = settings.ITSM_SYNC_CRONTAB
    if crontab:
        # 优先使用 crontab
        interval = None
    tasks = {
        task_name: {
            'task': sync_itsm_data.name,
            'interval': interval,
            'crontab': crontab,
            'enabled': True,
        }
    }
    create_or_update_celery_periodic_tasks(tasks)


@shared_task(verbose_name=_('Sync JumpServer data locally'))
def sync_itsm_sync_js_data():
    sync_other_js_data()


@shared_task(verbose_name=_('Registration periodic sync JumpServer data task'))
@after_app_ready_start
def sync_itsm_sync_js_data_periodic():
    if not settings.ITSM_SYNC_JS_DATA_ENABLED:
        return

    task_name = 'sync_itsm_sync_js_data_periodic'
    crontab = settings.ITSM_SYNC_JS_CRONTAB
    if crontab:
        interval = None
    tasks = {
        task_name: {
            'task': sync_itsm_sync_js_data.name,
            'interval': interval,
            'crontab': crontab,
            'enabled': True,
        }
    }
    create_or_update_celery_periodic_tasks(tasks)
