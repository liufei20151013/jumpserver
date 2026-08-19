import json
import os
import tarfile
import tempfile
import uuid

from celery.result import AsyncResult
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils._os import safe_join
from django.utils.translation import gettext_lazy as _
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from acls.models import LoginAssetACL
from assets.models import Asset
from common.const.http import POST
from common.permissions import IsValidUser, BootstrapTokenPermission
from common.utils import get_logger, get_request_ip_or_data
from ops.celery import app
from ops.const import Types, JobStatus
from ops.models import Job, JobExecution, JMSPermedInventory
from ops.serializers.job import (
    JobSerializer, JobExecutionSerializer, FileSerializer, JobTaskStopSerializer
)
from common.utils.endpoint_routing import (
    split_assets_by_endpoint, mark_batch_active, mark_child_executions,
    get_child_execution_ids,
)
from ops.utils import merge_nodes_and_assets, resolve_sync_path

__all__ = [
    'JobViewSet', 'JobExecutionViewSet', 'JobRunVariableHelpAPIView', 'JobExecutionTaskDetail', 'UsernameHintsAPI',
    'ClassifiedHostsAPI', 'JobUploadSrcApi'
]

from ops.tasks import run_ops_job_execution
from ops.variables import JMS_JOB_VARIABLE_HELP
from ops.const import COMMAND_EXECUTION_DISABLED
from orgs.mixins.api import OrgBulkModelViewSet
from orgs.utils import tmp_to_org, get_current_org
from accounts.models import Account
from assets.const import Protocol
from perms.const import ActionChoices
from perms.utils.asset_perm import PermAssetDetailUtil
from jumpserver.settings import get_file_md5

logger = get_logger(__file__)


def set_task_to_serializer_data(serializer, task_id):
    data = getattr(serializer, "_data", {})
    data["task_id"] = task_id
    setattr(serializer, "_data", data)


def _create_child_execution(parent):
    """为父执行创建一条子执行记录"""
    with tmp_to_org(parent.org):
        return JobExecution.objects.create(
            org_id=parent.org_id,
            job=parent.job,
            job_version=parent.job_version,
            parameters=parent.parameters,
            creator=parent.creator,
            material=parent.material,
            job_type=parent.job_type,
        )


def _dispatch_execution(execution, assets):
    """
    按端点拆分资产并分发 JobExecution。

    - 单分组 / 路由未启用：直接投递 execution 到对应队列（现有行为，task_id=execution.id）。
    - 多分组：execution 作为父执行（纯聚合节点，不投递执行），为每个分组创建子执行
      并投递到端点专属队列；父-子关系与批量元数据写 Redis。
    """
    # on_commit 回调可能在请求 org 上下文失效后执行，显式切回执行所属 org，
    # 保证 split_assets_by_endpoint 内 Asset 查询与子执行创建不受 org 隔离影响。
    with tmp_to_org(execution.org):
        asset_ids = [str(a.id) for a in assets]
        groups = split_assets_by_endpoint(asset_ids) if asset_ids else {'ansible': []}

        if len(groups) <= 1:
            queue = next(iter(groups), 'ansible')
            return run_ops_job_execution.apply_async(
                (str(execution.id),), queue=queue, task_id=str(execution.id)
            )

        # 多分组：父执行只作聚合，不实际执行（task_id 设为自己 id，供 stop/详情查询）
        execution.task_id = str(execution.id)
        execution.save(update_fields=['task_id'])

        child_ids = []
        for queue, group_asset_ids in groups.items():
            if not group_asset_ids:
                continue
            child = _create_child_execution(execution)
            run_ops_job_execution.apply_async(
                (str(child.id),),
                kwargs={'asset_ids': group_asset_ids},
                queue=queue,
                task_id=str(child.id),
            )
            child_ids.append(str(child.id))
            cache.set(f'task_batch_{child.id}', str(execution.id), 3600)

        cache.set(f'batch_tasks_{execution.id}', child_ids, 3600)
        mark_batch_active(str(execution.id))
        mark_child_executions(child_ids)
        return child_ids


def _iter_tar(path):
    """把目录打包为 tar 流式返回（落临时文件后分块读取，避免整包进内存）"""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.tar')
    try:
        with os.fdopen(tmp_fd, 'wb') as f, tarfile.open(fileobj=f, mode='w') as tar:
            tar.add(path, arcname=os.path.basename(path))
        with open(tmp_path, 'rb') as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class LoginAssetACLCheckMixin:

    def check_login_asset_acls(self, user, assets, account, ip):
        for asset in assets:
            kwargs = {'user': user, 'asset': asset, 'account_username': account}
            acls = LoginAssetACL.filter_queryset(**kwargs)
            acl = LoginAssetACL.get_match_rule_acls(user, ip, acls)
            if not acl:
                return
            if not acl.is_action(acl.ActionChoices.accept):
                raise PermissionDenied(_(
                    "Login to asset {}({}) is rejected by login asset ACL ({})".format(asset.name, asset.address, acl)
                ))


class JobViewSet(LoginAssetACLCheckMixin, OrgBulkModelViewSet):
    serializer_class = JobSerializer
    filterset_fields = ('name', 'type')
    search_fields = ('name', 'comment')
    model = Job
    _parameters = None

    def check_permissions(self, request):
        # job: upload_file
        if self.action == 'upload' or request.data.get('type') == Types.upload_file:
            return super().check_permissions(request)
        # job: adhoc, playbook
        if not settings.SECURITY_COMMAND_EXECUTION:
            return self.permission_denied(request, COMMAND_EXECUTION_DISABLED)
        return super().check_permissions(request)

    def check_upload_permission(self, assets, account_name):
        protocols_required = {Protocol.ssh, Protocol.sftp, Protocol.winrm}
        error_msg_missing_protocol = _(
            "Asset ({asset}) must have at least one of the following protocols added: SSH, SFTP, or WinRM")
        error_msg_auth_missing_protocol = _("Asset ({asset}) authorization is missing SSH, SFTP, or WinRM protocol")
        error_msg_auth_missing_upload = _("Asset ({asset}) authorization lacks upload permissions")
        for asset in assets:
            protocols = asset.protocols.values_list("name", flat=True)
            if not set(protocols).intersection(protocols_required):
                self.permission_denied(self.request, error_msg_missing_protocol.format(asset=asset.name))
            util = PermAssetDetailUtil(self.request.user, asset)
            if not util.check_perm_protocols(protocols_required):
                self.permission_denied(self.request, error_msg_auth_missing_protocol.format(asset=asset.name))
            if not util.check_perm_actions(account_name, [ActionChoices.upload.value]):
                self.permission_denied(self.request, error_msg_auth_missing_upload.format(asset=asset.name))

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset \
            .filter(creator=self.request.user) \
            .exclude(type=Types.upload_file)

        # Job 列表不显示 adhoc, retrieve 要取状态
        if self.action != 'retrieve':
            return queryset.filter(instant=False)
        return queryset

    def perform_create(self, serializer):
        run_after_save = serializer.validated_data.pop('run_after_save', False)
        self._parameters = serializer.validated_data.pop('parameters', None)
        nodes = serializer.validated_data.pop('nodes', [])
        assets = serializer.validated_data.get('assets', [])
        assets = merge_nodes_and_assets(nodes, assets, self.request.user)
        if serializer.validated_data.get('type') == Types.upload_file:
            account_name = serializer.validated_data.get('runas')
            self.check_upload_permission(assets, account_name)
        instance = serializer.save()

        if instance.instant or run_after_save:
            self.run_job(instance, serializer)

    def perform_update(self, serializer):
        run_after_save = serializer.validated_data.pop('run_after_save', False)
        self._parameters = serializer.validated_data.pop('parameters', None)
        instance = serializer.save()
        if run_after_save:
            self.run_job(instance, serializer)

    def run_job(self, job, serializer):
        execution = job.create_execution()
        if self._parameters:
            execution.parameters = JobExecutionSerializer.validate_parameters(self._parameters)
        execution.creator = self.request.user
        execution.save()
        assets = merge_nodes_and_assets(job.nodes.all(), job.assets.all(), self.request.user)
        self.check_login_asset_acls(
            self.request.user,
            assets,
            job.runas,
            get_request_ip_or_data(self.request)
        )

        set_task_to_serializer_data(serializer, execution.id)
        transaction.on_commit(
            lambda: _dispatch_execution(execution, assets)
        )

    @staticmethod
    def get_duplicates_files(files):
        seen = set()
        duplicates = set()
        for file in files:
            if file in seen:
                duplicates.add(file)
            else:
                seen.add(file)
        return list(duplicates)

    @staticmethod
    def get_exceeds_limit_files(files):
        exceeds_limit_files = []
        for file in files:
            if file.size > settings.FILE_UPLOAD_SIZE_LIMIT_MB * 1024 * 1024:
                exceeds_limit_files.append(file)
        return exceeds_limit_files

    @action(methods=[POST], detail=False, serializer_class=FileSerializer,
            permission_classes=[IsValidUser, ], url_path='upload')
    def upload(self, request, *args, **kwargs):
        uploaded_files = request.FILES.getlist('files')
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            msg = 'Upload data invalid: {}'.format(serializer.errors)
            return Response({'error': msg}, status=400)

        same_files = self.get_duplicates_files(uploaded_files)
        if same_files:
            return Response({'error': _("Duplicate file exists")}, status=400)

        exceeds_limit_files = self.get_exceeds_limit_files(uploaded_files)
        if exceeds_limit_files:
            return Response(
                {'error': _("File size exceeds maximum limit. Please select a file smaller than {limit}MB").format(
                    limit=settings.FILE_UPLOAD_SIZE_LIMIT_MB)},
                status=400)

        job_id = request.data.get('job_id', '')
        job = get_object_or_404(Job, pk=job_id, creator=request.user)
        job_args = json.loads(job.args)
        src_path_info = []
        upload_file_dir = safe_join(settings.SHARE_DIR, 'job_upload_file', job_id)
        for uploaded_file in uploaded_files:
            filename = uploaded_file.name
            saved_path = safe_join(upload_file_dir, f'{filename}')
            os.makedirs(os.path.dirname(saved_path), exist_ok=True)
            try:
                # 大文件（TemporaryUploadedFile）：multipart 已落盘到 FILE_UPLOAD_TEMP_DIR，
                # 与 SHARE_DIR 同文件系统时直接 rename（瞬时），省去 chunks() 的整文件拷贝
                temp_path = uploaded_file.temporary_file_path()
                os.replace(temp_path, saved_path)
            except (AttributeError, OSError):
                # 小文件在内存（InMemoryUploadedFile）或跨文件系统 rename 失败：回退逐块拷贝
                with open(saved_path, 'wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
            src_path_info.append({'filename': filename, 'md5': get_file_md5(saved_path)})
        job_args['src_path_info'] = src_path_info
        job.args = json.dumps(job_args)
        job.save()
        self.run_job(job, serializer)
        return Response({'task_id': serializer.data.get('task_id')}, status=201)


class JobExecutionViewSet(LoginAssetACLCheckMixin, OrgBulkModelViewSet):
    serializer_class = JobExecutionSerializer
    http_method_names = ('get', 'post', 'head', 'options',)
    model = JobExecution
    search_fields = ('material',)
    filterset_fields = ['status', 'job_id']

    def check_permissions(self, request):
        if not settings.SECURITY_COMMAND_EXECUTION:
            return self.permission_denied(request, COMMAND_EXECUTION_DISABLED)
        return super().check_permissions(request)

    @staticmethod
    def start_deploy(instance, serializer):
        run_ops_job_execution.apply_async((str(instance.id),), task_id=str(instance.id))

    def perform_create(self, serializer):
        job = serializer.validated_data.get('job')
        assets = []
        if job:
            assets = merge_nodes_and_assets(job.nodes.all(), list(job.assets.all()), self.request.user)
            self.check_login_asset_acls(
                self.request.user,
                assets,
                job.runas,
                get_request_ip_or_data(self.request)
            )

        instance = serializer.save()
        instance.job_version = instance.job.version
        instance.material = instance.job.material
        instance.job_type = Types[instance.job.type].value
        instance.creator = self.request.user
        instance.save()

        set_task_to_serializer_data(serializer, instance.id)
        transaction.on_commit(
            lambda: _dispatch_execution(instance, assets)
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(creator=self.request.user)
        # 隐藏子执行记录：父-子关系用 Redis 承载，子执行不单独展示在列表
        child_ids = get_child_execution_ids()
        if child_ids:
            queryset = queryset.exclude(id__in=child_ids)
        return queryset

    @action(methods=[POST], detail=False, serializer_class=JobTaskStopSerializer, permission_classes=[IsValidUser, ],
            url_path='stop')
    def stop(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response({'error': serializer.errors}, status=400)
        task_id = serializer.validated_data['task_id']
        try:
            user = request.user
            if user.has_perm("audits.view_joblog"):
                instance = get_object_or_404(JobExecution, task_id=task_id)
            else:
                instance = get_object_or_404(JobExecution, task_id=task_id, creator=request.user)
        except Http404:
            return Response(
                {'error': _("The task is being created and cannot be interrupted. Please try again later.")},
                status=400
            )

        # 父执行（多端点分发）：无真实 Celery 任务，转发 stop 到各子执行后结束父执行
        child_ids = cache.get(f'batch_tasks_{instance.id}') or []
        if child_ids:
            for child_id in child_ids:
                try:
                    child = JobExecution.objects.filter(id=child_id).first()
                    if child and not child.is_finished:
                        child.stop()
                except Exception:
                    logger.exception('Stop child execution %s failed', child_id)
            instance.stop()
            return Response({'task_id': task_id}, status=200)

        try:
            task = AsyncResult(task_id, app=app)
            inspect = app.control.inspect()

            for worker in inspect.registered().keys():
                if not worker.startswith('ansible'):
                    continue
                if task_id not in [at['id'] for at in inspect.active().get(worker, [])]:
                    # 在队列中未执行使用revoke执行
                    task.revoke(terminate=True)
                    instance.set_error('Job stop by "revoke task {}"'.format(task_id))
                    return Response({'task_id': task_id}, status=200)
        except Exception as e:
            instance.set_error(str(e))
            return Response({'error': f'Error while stopping the task {task_id}: {e}'}, status=400)

        instance.stop()
        return Response({'task_id': task_id}, status=200)


class JobExecutionTaskDetail(APIView):
    rbac_perms = {
        'GET': ['ops.view_jobexecution'],
    }

    @staticmethod
    def _aggregate_children(children):
        """聚合子执行状态：全部成功=success，有失败/超时优先，否则 running"""
        statuses = [c.status for c in children]
        if all(s == JobStatus.success for s in statuses):
            status = JobStatus.success
        elif any(s == JobStatus.failed for s in statuses):
            status = JobStatus.failed
        elif any(s == JobStatus.timeout for s in statuses):
            status = JobStatus.timeout
        else:
            status = JobStatus.running
        is_finished = status in (JobStatus.success, JobStatus.failed, JobStatus.timeout)
        is_success = status == JobStatus.success
        time_cost = max((c.time_cost for c in children), default=0)
        summary = {}
        for c in children:
            for k, v in (c.summary or {}).items():
                if isinstance(v, int):
                    summary[k] = summary.get(k, 0) + v
                elif k not in summary:
                    summary[k] = v
        return status, is_finished, is_success, time_cost, summary

    def get(self, request, **kwargs):
        org = get_current_org()
        task_id = str(kwargs.get('task_id'))

        with tmp_to_org(org):
            execution = get_object_or_404(JobExecution, pk=task_id, creator=request.user)
            child_ids = cache.get(f'batch_tasks_{task_id}') or []
            children = list(JobExecution.objects.filter(id__in=child_ids)) if child_ids else []

        if children:
            status, is_finished, is_success, time_cost, summary = self._aggregate_children(children)
        else:
            status = execution.status
            is_finished = execution.is_finished
            is_success = execution.is_success
            time_cost = execution.time_cost
            summary = execution.summary

        return Response(data={
            'status': {
                'value': status,
                'label': dict(JobStatus.choices).get(status, status)
            },
            'is_finished': is_finished,
            'is_success': is_success,
            'time_cost': time_cost,
            'job_id': execution.job.id,
            'summary': summary
        })


class JobUploadSrcApi(APIView):
    """
    文件同步源接口：子节点执行 upload/playbook 任务时，从主节点按 key 拉取文件目录 tar 流。

    鉴权复用 BOOTSTRAP_TOKEN（组件间同步），key 白名单见 `resolve_sync_path`。

    必须置空 authentication_classes：DRF 默认认证链（PrivateTokenAuthentication 等）
    会把 `Authorization: Token <BOOTSTRAP_TOKEN>` 当作用户令牌解析，匹配不上直接 401，
    导致自定义 permission 根本不会被调用。跳过认证后由 BootstrapTokenPermission 单独校验。
    """
    authentication_classes = ()
    permission_classes = (BootstrapTokenPermission,)

    def get(self, request, *args, **kwargs):
        key = request.query_params.get('key', '')
        path = resolve_sync_path(key)
        if not path or not os.path.isdir(path) or not os.listdir(path):
            raise Http404(_('File not found'))
        response = StreamingHttpResponse(_iter_tar(path), content_type='application/x-tar')
        response['Content-Disposition'] = 'attachment; filename="{}.tar"'.format(os.path.basename(path))
        return response


class JobRunVariableHelpAPIView(APIView):
    permission_classes = [IsValidUser]

    def get(self, request, **kwargs):
        return Response(data=JMS_JOB_VARIABLE_HELP)


class UsernameHintsAPI(APIView):
    permission_classes = [IsValidUser]

    def post(self, request, **kwargs):
        if settings.SAFE_MODE:
            return Response(data=[])
        node_ids = request.data.get('nodes', [])
        asset_ids = request.data.get('assets', [])
        query = request.data.get('query', None)

        assets = list(Asset.objects.filter(id__in=asset_ids).all())

        assets = merge_nodes_and_assets(node_ids, assets, request.user)

        top_accounts = Account.objects \
            .exclude(username__startswith='jms_') \
            .exclude(username__startswith='js_') \
            .filter(username__icontains=query) \
            .filter(asset__in=assets) \
            .values('username') \
            .annotate(total=Count('username')) \
            .order_by('-total', '-username')[:10]
        return Response(data=top_accounts)


class ClassifiedHostsAPI(APIView):
    permission_classes = [IsValidUser]

    def post(self, request, **kwargs):
        asset_ids = request.data.get('assets', [])
        node_ids = request.data.get('nodes', [])
        runas_policy = request.data.get('runas_policy', 'privileged_first')
        account_prefer = request.data.get('runas', 'root,Administrator')
        module = request.data.get('module', 'shell')
        assets = list(Asset.objects.filter(id__in=asset_ids).all())
        tmp_dir = os.path.join(settings.PROJECT_DIR, 'inventory', str(uuid.uuid4()))
        os.makedirs(tmp_dir, exist_ok=True)
        inventory = JMSPermedInventory(
            assets=assets,
            nodes=node_ids,
            module=module,
            account_policy=runas_policy,
            account_prefer=account_prefer,
            user=self.request.user
        )
        classified_hosts = inventory.get_classified_hosts(tmp_dir)

        return Response(data=classified_hosts)
