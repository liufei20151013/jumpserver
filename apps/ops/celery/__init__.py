# -*- coding: utf-8 -*-

import os

from celery import Celery
from kombu import Exchange, Queue

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jumpserver.settings')
from jumpserver import settings
from .heatbeat import *

# from django.conf import settings

app = Celery('jumpserver')

configs = {k: v for k, v in settings.__dict__.items() if k.startswith('CELERY')}
# Using a string here means the worker will not have to
# pickle the object when using Windows.
# app.config_from_object('django.conf:settings', namespace='CELERY')
celery_queues = [
    Queue("celery", Exchange("celery"), routing_key="celery"),
    Queue("ansible", Exchange("ansible"), routing_key="ansible"),
]

# 动态注册端点队列（基于 Endpoint 服务终端）
try:
    from terminal.models import Endpoint
    _endpoints = Endpoint.objects.filter(is_active=True).exclude(
        id=Endpoint.default_id
    )
    for _ep in _endpoints:
        _q = 'ansible_endpoint_{}'.format(
            _ep.name.lower().replace(' ', '_').replace('-', '_')
        )
        celery_queues.append(Queue(_q, Exchange(_q), routing_key=_q))
except Exception:
    pass

configs["CELERY_QUEUES"] = celery_queues

app.namespace = 'CELERY'
app.conf.update(configs)
app.autodiscover_tasks(lambda: [app_config.split('.')[0] for app_config in settings.INSTALLED_APPS])
