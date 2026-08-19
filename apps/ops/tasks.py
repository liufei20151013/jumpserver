# coding: utf-8
import datetime

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_celery_beat.models import PeriodicTask
from django.conf import settings

from common.const.crontab import CRONTAB_AT_AM_TWO
from common.utils import get_logger, get_object_or_none, get_log_keep_day
from ops.celery import app
from ops.const import Types
from ops.serializers.job import JobExecutionSerializer
from orgs.utils import tmp_to_org, tmp_to_root_org
from .celery.decorator import (
    register_as_period_task, after_app_ready_start
)
from .celery.utils import (
    create_or_update_celery_periodic_tasks, get_celery_periodic_task,
    disable_celery_periodic_task, delete_celery_periodic_task
)
from .models import Job, JobExecution
from .utils import ensure_local_dir
from .notifications import ServerPerformanceCheckUtil
from common.utils.endpoint_routing import prune_child_execution_ids

logger = get_logger(__file__)


def job_task_activity_callback(self, job_id, *args, **kwargs):
    job = get_object_or_none(Job, id=job_id)
    if not job:
        return
    resource_ids = [job.id]
    org_id = job.org_id
    return resource_ids, org_id


def _ensure_local_files(execution):
    """
    端点执行 upload/playbook 前，从主节点拉取文件目录到本地。

    仅 upload_file / playbook 类型需要文件输入；ensure_local_dir 对本地已存在
    的目录幂等跳过（兼容共享存储与主节点自身执行）。拉取失败时抛异常中止任务，
    避免在文件缺失的情况下继续执行 Ansible（否则报错会变成误导性的
    "Could not find ... on the Ansible Controller"）。
    """
    try:
        job = execution.current_job
    except Exception:
        raise RuntimeError('Failed to resolve job for file synchronization')
    if execution.job_type == Types.upload_file:
        ok = ensure_local_dir('job_upload_file/{}'.format(job.id))
        if not ok:
            raise RuntimeError(
                'Failed to sync job upload files from core: job_upload_file/{}'.format(job.id)
            )
    elif execution.job_type == Types.playbook:
        playbook = getattr(job, 'playbook', None)
        if playbook:
            ok = ensure_local_dir('ops/playbook/{}'.format(playbook.id))
            if not ok:
                raise RuntimeError(
                    'Failed to sync playbook files from core: ops/playbook/{}'.format(playbook.id)
                )


def _run_ops_job_execution(execution, asset_ids=None):
    try:
        with tmp_to_org(execution.org):
            _ensure_local_files(execution)
            execution.start(asset_ids=asset_ids)
    except SoftTimeLimitExceeded:
        execution.set_error('Run timeout')
        logger.error("Run adhoc timeout")
    except Exception as e:
        execution.set_error(e)
        logger.error("Start adhoc execution error: {}".format(e))


@shared_task(
    soft_time_limit=60,
    queue="ansible",
    verbose_name=_("Run ansible task"),
    activity_callback=job_task_activity_callback,
    description=_(
        "Execute scheduled adhoc and playbooks, periodically invoking the task for execution"
    )
)
def run_ops_job(job_id):
    with tmp_to_root_org():
        job = get_object_or_none(Job, id=job_id)
    if not job:
        logger.error("Did not get the execution: {}".format(job_id))
        return
    if not settings.SECURITY_COMMAND_EXECUTION and job.type != Types.upload_file:
        return
    with tmp_to_org(job.org):
        execution = job.create_execution()
        execution.creator = job.creator
        if job.periodic_variable:
            execution.parameters = JobExecutionSerializer.validate_parameters(job.periodic_variable)
        _run_ops_job_execution(execution)


def job_execution_task_activity_callback(self, execution_id, *args, **kwargs):
    execution = get_object_or_none(JobExecution, id=execution_id)
    if not execution:
        return
    resource_ids = [execution.id]
    org_id = execution.org_id
    return resource_ids, org_id


@shared_task(
    soft_time_limit=60,
    queue="ansible",
    verbose_name=_("Run ansible task execution"),
    activity_callback=job_execution_task_activity_callback,
    description=_(
        "Execute the task when manually adhoc or playbooks"
    )
)
def run_ops_job_execution(execution_id, **kwargs):
    asset_ids = kwargs.get('asset_ids')
    with tmp_to_root_org():
        execution = get_object_or_none(JobExecution, id=execution_id)
    if not execution:
        logger.error("Did not get the execution: {}".format(execution_id))
        return
    if not settings.SECURITY_COMMAND_EXECUTION and execution.job.type != Types.upload_file:
        return
    _run_ops_job_execution(execution, asset_ids=asset_ids)


@shared_task(
    verbose_name=_('Clear celery periodic tasks'),
    description=_(
        "At system startup, clean up celery tasks that no longer exist"
    )
)
@after_app_ready_start
def clean_celery_periodic_tasks():
    """清除celery定时任务"""
    logger.info('Start clean celery periodic tasks.')
    register_tasks = PeriodicTask.objects.all()
    for task in register_tasks:
        if task.task in app.tasks:
            continue

        task_name = task.name
        logger.info('Start clean task: {}'.format(task_name))
        disable_celery_periodic_task(task_name)
        delete_celery_periodic_task(task_name)
        task = get_celery_periodic_task(task_name)
        if task is None:
            logger.info('Clean task success: {}'.format(task_name))
        else:
            logger.info('Clean task failure: {}'.format(task))


@shared_task(
    verbose_name=_('Create or update periodic tasks'),
    description=_(
        """With version iterations, new tasks may be added, or task names and execution times may 
        be modified. Therefore, upon system startup, tasks will be registered or the parameters 
        of scheduled tasks will be updated"""
    )
)
@after_app_ready_start
def create_or_update_registered_periodic_tasks():
    from .celery.decorator import get_register_period_tasks
    for task in get_register_period_tasks():
        create_or_update_celery_periodic_tasks(task)


@shared_task(
    verbose_name=_("Periodic check service performance"),
    description=_(
        """Check every hour whether each component is offline and whether the CPU, memory, 
        and disk usage exceed the thresholds, and send an alert message to the administrator"""
    )
)
@register_as_period_task(interval=3600)
def check_server_performance_period():
    ServerPerformanceCheckUtil().check_and_publish()


@shared_task(
    verbose_name=_("Clean up unexpected jobs"),
    description=_(
        """Due to exceptions caused by executing adhoc and playbooks in the Job Center, 
        which result in the task status not being updated, the system will clean up abnormal jobs 
        that have not been completed for more than 3 hours every hour and mark these tasks as 
        failed"""
    )
)
@register_as_period_task(interval=3600)
def clean_up_unexpected_jobs():
    with tmp_to_root_org():
        JobExecution.clean_unexpected_execution()


@shared_task(
    verbose_name=_('Clean job_execution db record'),
    description=_(
        """Due to the execution of adhoc and playbooks in the Job Center, execution records will 
        be generated. The system will clean up records that exceed the retention period every day 
        at 2 a.m., based on the configuration of 'System Settings - Tasks - Regular clean-up - 
        Job execution retention days'"""
    )
)
@register_as_period_task(crontab=CRONTAB_AT_AM_TWO)
def clean_job_execution_period():
    logger.info("Start clean job_execution db record")
    now = timezone.now()
    days = get_log_keep_day('JOB_EXECUTION_KEEP_DAYS')
    expired_day = now - datetime.timedelta(days=days)
    with tmp_to_root_org():
        del_res = JobExecution.objects.filter(date_created__lt=expired_day).delete()
        logger.info(
            f"clean job_execution db record success! delete {days} days {del_res[0]} records")
    # 清理 Redis 子执行集合中已随记录一并删除的 id，避免列表过滤累积失效 id
    prune_child_execution_ids()

# 测试使用，注释隐藏
# @shared_task
# def longtime_add(x, y):
#     print('long time task begins')
#     time.sleep(50)
#     print('long time task finished')
#     return x + y
