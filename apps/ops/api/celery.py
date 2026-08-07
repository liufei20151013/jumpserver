# -*- coding: utf-8 -*-
#
import os
import re
from collections import defaultdict

from celery.result import AsyncResult
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from django_celery_beat.models import PeriodicTask
from django_filters import rest_framework as drf_filters
from rest_framework import generics, viewsets, mixins, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from common.api import LogTailApi, CommonApiMixin
from common.drf.filters import BaseFilterSet
from common.exceptions import JMSException
from common.permissions import IsValidUser
from common.utils import get_logger
from common.utils.timezone import local_now
from ops.celery import app
from ..ansible.utils import get_ansible_task_log_path
from ..batch_log import (
    append_batch_block, buffer_task_lines, filter_subtask_lines,
    get_subtask_summaries, get_task_lines, render_summary,
    stash_subtask_summary, write_batch_header,
)
from ..celery.utils import get_celery_task_log_path
from ..const import CELERY_LOG_MAGIC_MARK
from ..models import CeleryTaskExecution, CeleryTask
from ..serializers import CeleryResultSerializer, CeleryPeriodTaskSerializer
from ..serializers.celery import CeleryTaskSerializer, CeleryTaskExecutionSerializer

logger = get_logger(__name__)

__all__ = [
    'CeleryTaskExecutionLogApi', 'CeleryResultApi', 'CeleryPeriodTaskViewSet',
    'AnsibleTaskLogApi', 'CeleryTaskViewSet', 'CeleryTaskExecutionViewSet',
    'TaskLogSyncApi'
]


class CeleryTaskExecutionLogApi(LogTailApi):
    permission_classes = (IsValidUser,)
    task = None
    task_id = ''
    pattern = re.compile(r'Task .* succeeded in \d+\.\d+s.*')

    def get(self, request, *args, **kwargs):
        self.task_id = str(kwargs.get('pk'))
        self.task = AsyncResult(self.task_id)
        return super().get(request, *args, **kwargs)

    def filter_line(self, line):
        if self.pattern.match(line):
            line = self.pattern.sub(line, '')
        return line

    def get_log_path(self):
        new_path = get_celery_task_log_path(self.task_id)
        if new_path and os.path.isfile(new_path):
            return new_path

        try:
            task = CeleryTaskExecution.objects.get(id=self.task_id)
        except CeleryTaskExecution.DoesNotExist:
            return None
        # 增量同步任务：日志由副节点推送后本节点会产生文件；
        # 尚未同步完成时按 task id 推算路径，交由 LogTailApi 等待
        return get_celery_task_log_path(self.task_id)

    def is_file_finish_write(self):
        return self.task.ready()

    def get_no_file_message(self, request):
        if self.mark == 'undefined':
            return '.'
        else:
            return _('Waiting task start')


class TaskLogSyncPermission(permissions.BasePermission):
    """校验副节点增量推送的鉴权令牌（复用 BOOTSTRAP_TOKEN）"""

    def has_permission(self, request, view):
        token = request.META.get('HTTP_X_JMS_LOG_TOKEN', '')
        expected = getattr(settings, 'BOOTSTRAP_TOKEN', '') or ''
        return bool(expected) and token == expected


class TaskLogSyncApi(APIView):
    """
    接收副节点(Celery Worker)增量推送的任务日志（当前仅连通性测试）。

    日志片段按 task_id 追加到本地日志文件；批量任务同时聚合到 batch 聚合文件；
    done 时写完成标记，使主节点 WebSocket/API 直接读本地文件实现实时回显，
    从而将日志移出 Redis 热路径。
    """
    permission_classes = (TaskLogSyncPermission,)

    @staticmethod
    def _write_all(fd, data):
        if isinstance(data, str):
            data = data.encode('utf-8', errors='ignore')
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]

    @classmethod
    def _append_to_file(cls, path, lines, append_magic=False):
        if not lines and not append_magic:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # O_APPEND 单次写原子，保证多个副节点并发聚合批量文件时不交错
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            for line in lines:
                if line:
                    cls._write_all(fd, line)
            if append_magic:
                cls._write_all(fd, CELERY_LOG_MAGIC_MARK)
        finally:
            os.close(fd)

    @staticmethod
    def _is_batch(batch_id):
        try:
            from django.core.cache import cache
            return bool(cache.get(f'batch_tasks_{batch_id}'))
        except Exception:
            return False

    @classmethod
    def _done_marker_path(cls, task_id):
        return get_celery_task_log_path(task_id) + '.done'

    @classmethod
    def _mark_task_done(cls, task_id):
        """写完成标记文件（替代 Redis done 键，跨进程安全）"""
        path = cls._done_marker_path(task_id)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write('done')
        except Exception:
            pass

    @classmethod
    def _all_subtasks_done(cls, batch_id):
        """判断批量任务的所有子任务是否都已完成（子任务 done POST 处理完毕并落盘后才有标记）"""
        try:
            from django.core.cache import cache
            task_ids = cache.get(f'batch_tasks_{batch_id}') or []
        except Exception:
            return False
        if not task_ids:
            return False
        for tid in task_ids:
            if not os.path.isfile(cls._done_marker_path(tid)):
                return False
        return True

    def post(self, request):
        task_id = request.data.get('task_id')
        if not task_id:
            return Response({'error': 'task_id required'}, status=status.HTTP_400_BAD_REQUEST)
        lines = request.data.get('lines') or []
        done = bool(request.data.get('done'))
        local = bool(request.data.get('local'))
        batch_id = request.data.get('batch_id')

        try:
            # 1) 子任务本地日志文件（remote 执行：副节点推送、主节点落盘；local 跳过，本机已写）
            if not local:
                self._append_to_file(get_celery_task_log_path(task_id), lines, append_magic=done)

            # 2) 完成标记（非批量任务直接标记；批量任务在自身内容落盘后再标记，
            #    避免并发完成时另一子任务提前触发 finish 而漏掉本任务内容）
            if done and not batch_id:
                self._mark_task_done(task_id)

            # 3) 批量聚合：缓冲去交错，子任务完成时追加其 PLAY 内容，全部完成后合并 Summary
            if batch_id and self._is_batch(batch_id):
                batch_path = get_celery_task_log_path(batch_id)
                write_batch_header(batch_path)
                buffer_task_lines(task_id, lines)
                # 已完成过的子任务（如 HTTP 重试重复推送）直接跳过，避免重复追加
                if done and not os.path.isfile(self._done_marker_path(task_id)):
                    play_lines, summary = filter_subtask_lines(get_task_lines(task_id))
                    if play_lines:
                        append_batch_block(batch_path, play_lines)
                    if summary:
                        stash_subtask_summary(batch_id, summary)
                    self._mark_task_done(task_id)
                    if self._all_subtasks_done(batch_id):
                        self._finish_batch(batch_path, batch_id)
        except Exception as e:
            logger.error('Task log sync failed for task {}: {}'.format(task_id, e))
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'ok': True})

    def _finish_batch(self, batch_path, batch_id):
        """
        批量任务全部子任务完成后：合并各子任务 Summary 并写结束标记。

        用 O_EXCL 创建完成标记作为互斥，避免并发 POST 重复完成。
        """
        marker = self._done_marker_path(batch_id)
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return
        try:
            os.write(fd, b'done')
        finally:
            os.close(fd)
        try:
            summary_lines = render_summary(get_subtask_summaries(batch_id))
            self._append_to_file(batch_path, summary_lines, append_magic=True)
        except Exception as e:
            logger.error('Finish batch log failed for batch {}: {}'.format(batch_id, e))
            # 兜底：确保 WebSocket 能读到结束标记
            try:
                self._append_to_file(batch_path, [], append_magic=True)
            except Exception:
                pass


class AnsibleTaskLogApi(LogTailApi):
    permission_classes = (IsValidUser,)

    def get_log_path(self):
        new_path = get_ansible_task_log_path(self.kwargs.get('pk'))
        if new_path and os.path.isfile(new_path):
            return new_path

    def get_no_file_message(self, request):
        if self.mark == 'undefined':
            return '.'
        else:
            return _('Waiting task start')


class CeleryResultApi(generics.RetrieveAPIView):
    permission_classes = (IsValidUser,)
    serializer_class = CeleryResultSerializer

    def get_object(self):
        pk = self.kwargs.get('pk')
        return AsyncResult(str(pk))


class CeleryPeriodTaskViewSet(CommonApiMixin, viewsets.ModelViewSet):
    queryset = PeriodicTask.objects.all()
    serializer_class = CeleryPeriodTaskSerializer
    http_method_names = ('get', 'head', 'options', 'patch')
    lookup_field = 'name'
    lookup_value_regex = '[\w.@]+'

    def get_object(self):
        name = self.kwargs.get('name')
        obj = get_object_or_404(PeriodicTask, name=name)
        return obj


class CelerySummaryAPIView(generics.RetrieveAPIView):
    def get(self, request, *args, **kwargs):
        pass


class CeleryTaskFilterSet(BaseFilterSet):
    name = drf_filters.CharFilter(method='filter_name')

    @staticmethod
    def filter_name(queryset, name, value):
        _ids = []
        for task in queryset:
            comment = task.meta.get('comment')
            if not comment:
                continue
            if value not in comment:
                continue
            _ids.append(task.id)
        queryset = queryset.filter(id__in=_ids)
        return queryset

    class Meta:
        model = CeleryTask
        fields = ['name']


class CeleryTaskViewSet(
    CommonApiMixin, mixins.RetrieveModelMixin,
    mixins.ListModelMixin, mixins.DestroyModelMixin,
    viewsets.GenericViewSet
):
    search_fields = ('name',)
    filterset_class = CeleryTaskFilterSet
    serializer_class = CeleryTaskSerializer

    def get_queryset(self):
        return CeleryTask.objects.exclude(name__startswith='celery')

    @staticmethod
    def extract_schedule(input_string):
        pattern = r'(\S+ \S+ \S+ \S+ \S+).*'
        match = re.match(pattern, input_string)
        if match:
            return match.group(1)
        else:
            return input_string

    def generate_execute_time(self, queryset):
        now = local_now()
        for i in queryset:
            task = getattr(i, 'periodic_obj', None)
            if not task:
                continue
            i.exec_cycle = self.extract_schedule(str(task.scheduler))
            last_run_at = task.last_run_at or now
            next_run_at = task.schedule.remaining_estimate(last_run_at)
            if next_run_at.total_seconds() < 0:
                next_run_at = task.schedule.remaining_estimate(now)
            i.next_exec_time = now + next_run_at
            i.enabled = task.enabled
        return queryset

    def generate_summary_state(self, execution_qs):
        model = self.get_queryset().model
        executions = execution_qs.order_by('-date_published').values('name', 'state')
        summary_state_dict = defaultdict(
            lambda: {
                'states': [], 'state': 'green',
                'summary': {'total': 0, 'success': 0}
            }
        )
        for execution in executions:
            name = execution['name']
            state = execution['state']

            summary = summary_state_dict[name]['summary']

            summary['total'] += 1
            summary['success'] += 1 if state == 'SUCCESS' else 0

            states = summary_state_dict[name].get('states')
            if states is not None and len(states) >= 5:
                color = model.compute_state_color(states)
                summary_state_dict[name]['state'] = color
                summary_state_dict[name].pop('states', None)
            elif isinstance(states, list):
                states.append(state)

        return summary_state_dict

    def loading_summary_state(self, queryset):
        if isinstance(queryset, list):
            names = [i.name for i in queryset]
            execution_qs = CeleryTaskExecution.objects.filter(name__in=names)
        else:
            execution_qs = CeleryTaskExecution.objects.all()
        summary_state_dict = self.generate_summary_state(execution_qs)
        for i in queryset:
            i.summary = summary_state_dict.get(i.name, {}).get('summary', {})
            i.state = summary_state_dict.get(i.name, {}).get('state', 'green')
        return queryset

    def filter_queryset(self, queryset):
        search = self.request.query_params.get('search')
        if search:
            queryset = CeleryTaskFilterSet.filter_name(queryset, 'name', search)
        else:
            queryset = super().filter_queryset(queryset)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        queryset = self.mark_periodic_and_sorted(queryset)

        page = self.paginate_queryset(queryset)
        if page is not None:
            page = self.generate_execute_time(page)
            page = self.loading_summary_state(page)
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        queryset = self.generate_execute_time(queryset)
        queryset = self.loading_summary_state(queryset)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @staticmethod
    def mark_periodic_and_sorted(queryset):
        names = queryset.values_list('name', flat=True)
        periodic_tasks = PeriodicTask.objects.filter(name__in=names)
        periodic_task_dict = {task.task: task for task in periodic_tasks}
        for q in queryset:
            if q.name in periodic_task_dict:
                q.periodic_obj = periodic_task_dict[q.name]
                q.is_periodic = True
            else:
                q.is_periodic = False
        queryset = sorted(queryset, key=lambda x: x.is_periodic, reverse=True)
        return queryset


class CeleryTaskExecutionViewSet(CommonApiMixin, viewsets.ModelViewSet):
    serializer_class = CeleryTaskExecutionSerializer
    http_method_names = ('get', 'post', 'head', 'options',)
    queryset = CeleryTaskExecution.objects.all()
    search_fields = ('id',)

    def get_queryset(self):
        task_id = self.request.query_params.get('task_id')
        if task_id:
            task = get_object_or_404(CeleryTask, id=task_id)
            self.queryset = self.queryset.filter(name=task.name)
        if not self.request.user.is_superuser:
            self.queryset = self.queryset.filter(creator=self.request.user)
        return self.queryset

    def create(self, request, *args, **kwargs):
        form_id = self.request.query_params.get('from', None)
        if not form_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        execution = get_object_or_404(CeleryTaskExecution, id=form_id)
        task = app.tasks.get(execution.name, None)
        if not task:
            msg = _("Task {} not found").format(execution.name)
            raise JMSException(code='task_not_found_error', detail=msg)
        try:
            execution.kwargs.pop('__current_lang', None)
            execution.kwargs.pop('__current_org_id', None)
            t = task.delay(*execution.args, **execution.kwargs)
        except TypeError:
            msg = _("Task {} args or kwargs error").format(execution.name)
            raise JMSException(code='task_args_error', detail=msg)
        return Response(status=status.HTTP_201_CREATED, data={'task_id': t.id})
