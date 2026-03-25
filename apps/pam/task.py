from celery import shared_task
from django.utils.translation import gettext_lazy as _

from common.utils import get_logger
from pam.main import process_data
from ops.celery.decorator import after_app_ready_start
from ops.celery.utils import disable_celery_periodic_task, create_or_update_celery_periodic_tasks
from django.conf import settings

logger = get_logger(__name__)


@shared_task(verbose_name=_('Sync pam full data to JumpServer'))
def sync_pam_full_data():
    process_data(True)


@shared_task(verbose_name=_('Registration periodic sync pam full data task'))
@after_app_ready_start
def sync_pam_full_data_periodic():
    if not settings.PAM_ENABLED:
        return
    task_name = 'sync_pam_full_data_periodic'

    try:
        disable_celery_periodic_task(task_name)
    except Exception as e:
        print('sync_pam_full_data_periodic does not exist')

    crontab = settings.PAM_FULL_DATA_SYNC_CRONTAB
    if crontab:
        tasks = {
            task_name: {
                'task': sync_pam_full_data.name,
                'interval': None,
                'crontab': crontab,
                'enabled': True,
            }
        }
        create_or_update_celery_periodic_tasks(tasks)


@shared_task(verbose_name=_('Sync pam incremental data to JumpServer'))
def sync_pam_incremental_data():
    process_data(False)


@shared_task(verbose_name=_('Registration periodic sync pam incremental data task'))
@after_app_ready_start
def sync_pam_incremental_data_periodic():
    if not settings.PAM_ENABLED:
        return
    task_name = 'sync_pam_incremental_data_periodic'

    try:
        disable_celery_periodic_task(task_name)
    except Exception as e:
        print('sync_pam_incremental_data_periodic does not exist')

    crontab = settings.PAM_INCREMENTAL_DATA_SYNC_CRONTAB
    if crontab:
        tasks = {
            task_name: {
                'task': sync_pam_incremental_data.name,
                'interval': None,
                'crontab': crontab,
                'enabled': True,
            }
        }
        create_or_update_celery_periodic_tasks(tasks)
