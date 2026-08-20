# ~*~ coding: utf-8 ~*~
from django.utils.translation import gettext as _
from django.views.generic.detail import SingleObjectMixin
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView, Response

from assets.tasks import test_gateways_connectivity_manual
from common.utils import get_logger
from orgs.mixins.api import OrgBulkModelViewSet
from .asset import HostViewSet
from .asset.asset import AssetsTaskMixin
from .. import serializers
from ..models import Zone, Gateway

logger = get_logger(__file__)
__all__ = ['ZoneViewSet', 'GatewayViewSet', "GatewayTestConnectionApi"]


class ZoneViewSet(OrgBulkModelViewSet):
    model = Zone
    filterset_fields = ("name",)
    search_fields = filterset_fields
    serializer_classes = {
        'default': serializers.ZoneSerializer,
        'list': serializers.ZoneListSerializer,
    }

    def get_serializer_class(self):
        if self.request.query_params.get('gateway'):
            return serializers.ZoneWithGatewaySerializer
        return super().get_serializer_class()

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


class GatewayViewSet(HostViewSet):
    perm_model = Gateway
    filterset_fields = ("zone__name", "name", "zone")
    search_fields = ("zone__name",)

    def get_serializer_classes(self):
        serializer_classes = super().get_serializer_classes()
        serializer_classes['default'] = serializers.GatewaySerializer
        return serializer_classes

    def get_queryset(self):
        queryset = Zone.get_gateway_queryset()
        return queryset


class GatewayTestConnectionApi(SingleObjectMixin, APIView):
    rbac_perms = {
        'POST': 'assets.test_assetconnectivity'
    }

    def get_queryset(self):
        queryset = Zone.get_gateway_queryset()
        return queryset

    def post(self, request, *args, **kwargs):
        gateway = self.get_object()
        local_port = self.request.data.get('port') or gateway.port
        try:
            local_port = int(local_port)
        except ValueError:
            raise ValidationError({'port': _('Number required')})
        tasks = test_gateways_connectivity_manual([gateway.id], local_port)
        # 端点路由启用后 dispatch 返回的是 list[AsyncResult]（每个端点队列一个任务）
        if isinstance(tasks, list):
            if len(tasks) > 1:
                # 多端点批量任务：优先返回 batch_id，前端订阅聚合日志
                batch_id = AssetsTaskMixin._get_batch_id_for_tasks(tasks)
                task_id = batch_id or tasks[0].id
            else:
                task_id = tasks[0].id
        else:
            task_id = tasks.id
        return Response({'task': task_id})
