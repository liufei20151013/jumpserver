from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from assets.models import Asset
from authentication.permissions import IsValidUserOrConnectionToken
from common.api import JMSBulkModelViewSet
from common.utils.endpoint_routing import get_client_connect_port
from orgs.utils import tmp_to_root_org
from terminal import serializers
from terminal.models import Session, Endpoint, EndpointRule

__all__ = ['EndpointViewSet', 'EndpointRuleViewSet']


class SmartEndpointViewMixin:
    get_serializer: callable
    request: Request

    # View 处理过程中用的属性
    target_instance: None
    target_protocol: None

    @action(methods=['get'], detail=False, permission_classes=[IsValidUserOrConnectionToken])
    @tmp_to_root_org()
    def smart(self, request, *args, **kwargs):
        self.target_instance = self.get_target_instance()
        self.target_protocol = self.get_target_protocol()
        if not self.target_protocol:
            error = _('Not found protocol query params')
            return Response(data={'error': error}, status=status.HTTP_404_NOT_FOUND)
        endpoint = self.match_endpoint()
        serializer = self.get_serializer(endpoint)
        data = serializer.data
        # 客户端 / 向导展示的连接端口统一为集控入口端口（SSH 先连集控 KoKo 经
        # 伪网关隧道到区域 KoKo；DB 先连集控 magnus 经伪网关隧道连库），
        # 未命中替换条件时保持端点原端口
        master_port = get_client_connect_port(endpoint, self.target_instance, self.target_protocol)
        if master_port:
            # ssh/telnet/sftp 的端口字段统一为 ssh_port，DB 协议为 {protocol}_port
            if self.target_protocol in ('ssh', 'telnet', 'sftp'):
                data['ssh_port'] = master_port
            else:
                data[f'{self.target_protocol}_port'] = master_port
        return Response(data)

    def match_endpoint(self):
        endpoint = self.match_endpoint_by_label()
        if not endpoint:
            endpoint = self.match_endpoint_by_target_ip()
        return endpoint

    def match_endpoint_by_label(self):
        return Endpoint.match_by_instance_label(self.target_instance, self.target_protocol, self.request)

    def match_endpoint_by_target_ip(self):
        target_ip = self.request.GET.get('target_ip', '')  # 支持target_ip参数，用来方便测试
        if not target_ip and callable(getattr(self.target_instance, 'get_target_ip', None)):
            target_ip = self.target_instance.get_target_ip()
        endpoint = EndpointRule.match_endpoint(
            self.target_instance, target_ip, self.target_protocol, self.request
        )
        return endpoint

    def get_target_instance(self):
        request = self.request
        asset_id = request.GET.get('asset_id')
        session_id = request.GET.get('session_id')
        token_id = request.GET.get('token')

        if token_id:
            from authentication.models import ConnectionToken
            token = ConnectionToken.objects.filter(id=token_id).first()
            if token and token.asset:
                asset_id = token.asset.id
        if asset_id:
            pk, model = asset_id, Asset
        elif session_id:
            pk, model = session_id, Session
        else:
            pk, model = None, None
        if not pk or not model:
            return None
        with tmp_to_root_org():
            instance = get_object_or_404(model, pk=pk)
            return instance

    def get_target_protocol(self):
        protocol = None
        if not protocol:
            protocol = self.request.GET.get('protocol')
        return protocol


class EndpointViewSet(SmartEndpointViewMixin, JMSBulkModelViewSet):
    filterset_fields = ('name', 'host')
    search_fields = filterset_fields
    serializer_class = serializers.EndpointSerializer
    queryset = Endpoint.objects.all()


class EndpointRuleViewSet(JMSBulkModelViewSet):
    filterset_fields = ('name',)
    search_fields = filterset_fields
    serializer_class = serializers.EndpointRuleSerializer
    queryset = EndpointRule.objects.all()
