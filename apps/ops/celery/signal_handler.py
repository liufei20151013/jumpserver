# -*- coding: utf-8 -*-
#
import logging

from celery import subtask
from celery.signals import (
    worker_ready, worker_shutdown, after_setup_logger
)
from django.core.cache import cache
from django_celery_beat.models import PeriodicTask

from common.utils import get_logger
from .decorator import get_after_app_ready_tasks, get_after_app_shutdown_clean_tasks
from .logger import CeleryThreadTaskFileHandler

logger = get_logger(__file__)
safe_str = lambda x: x


@worker_ready.connect
def on_app_ready(sender=None, headers=None, **kwargs):
    if cache.get("CELERY_APP_READY", 0) == 1:
        return
    cache.set("CELERY_APP_READY", 1, 10)
    tasks = get_after_app_ready_tasks()
    logger.debug("Work ready signal recv")
    logger.debug("Start need start task: [{}]".format(", ".join(tasks)))
    for task in tasks:
        periodic_task = PeriodicTask.objects.filter(task=task).first()
        if periodic_task and not periodic_task.enabled:
            logger.debug("Periodic task [{}] is disabled!".format(task))
            continue
        subtask(task).delay()


@worker_shutdown.connect
def after_app_shutdown_periodic_tasks(sender=None, **kwargs):
    if cache.get("CELERY_APP_SHUTDOWN", 0) == 1:
        return
    cache.set("CELERY_APP_SHUTDOWN", 1, 10)
    tasks = get_after_app_shutdown_clean_tasks()
    logger.debug("Worker shutdown signal recv")
    logger.debug("Clean period tasks: [{}]".format(', '.join(tasks)))
    PeriodicTask.objects.filter(name__in=tasks).delete()


_task_log_handler = None


@after_setup_logger.connect
def add_celery_logger_handler(sender=None, logger=None, loglevel=None, format=None, **kwargs):
    global _task_log_handler
    if not logger:
        return
    # 复用已创建的 handler：避免重复实例各自写文件/各自推送日志
    if _task_log_handler is None:
        _task_log_handler = CeleryThreadTaskFileHandler()
    task_handler = _task_log_handler
    task_handler.setLevel(loglevel)
    formatter = logging.Formatter(format)
    task_handler.setFormatter(formatter)
    logger.addHandler(task_handler)
