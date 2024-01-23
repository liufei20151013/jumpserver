from celery import shared_task
from django.utils.translation import gettext_lazy as _

from common.utils import get_logger
from itsm.main import process_data
from ops.celery.decorator import after_app_ready_start
from ops.celery.utils import disable_celery_periodic_task, create_or_update_celery_periodic_tasks
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

    try:
        disable_celery_periodic_task(task_name)
    except Exception as e:
        print('sync_itsm_data_periodic does not exist')

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
