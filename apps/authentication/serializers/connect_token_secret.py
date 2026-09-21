from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from accounts.const import SecretType
from accounts.models import Account
from acls.models import CommandGroup, CommandFilterACL, DataMaskingRule
from assets.models import Asset, Platform, Gateway, Zone
from assets.serializers.asset import AssetProtocolsSerializer
from assets.serializers.platform import PlatformSerializer
from common.serializers.fields import LabeledChoiceField
from common.serializers.fields import ObjectRelatedField
from orgs.mixins.serializers import OrgResourceModelSerializerMixin
from perms.serializers.permission import ActionChoicesField
from terminal.connect_methods import NO_ENDPOINT_GATEWAY_METHODS, WebMethod
from users.models import User
from ..models import ConnectionToken

__all__ = [
    'ConnectionTokenSecretSerializer', 'ConnectTokenAppletOptionSerializer',
    'ConnectTokenVirtualAppOptionSerializer',
]


class _ConnectionTokenUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'name', 'username', 'email']


class _ConnectionTokenAssetSerializer(serializers.ModelSerializer):
    protocols = AssetProtocolsSerializer(many=True, required=False, label=_('Protocols'))
    info = serializers.DictField()

    class Meta:
        model = Asset
        fields = [
            'id', 'name', 'address', 'protocols', 'category',
            'type', 'org_id', 'info', 'secret_info', 'spec_info'
        ]


class _SimpleAccountSerializer(serializers.ModelSerializer):
    secret_type = LabeledChoiceField(choices=SecretType.choices, required=False, label=_('Secret type'))
    username = serializers.CharField(label=_('Username'), source='full_username', read_only=True)

    class Meta:
        model = Account
        fields = ['name', 'username', 'secret_type', 'secret']


class _ConnectionTokenAccountSerializer(serializers.ModelSerializer):
    su_from = serializers.SerializerMethodField(label=_('Su from'))
    secret_type = LabeledChoiceField(choices=SecretType.choices, required=False, label=_('Secret type'))
    username = serializers.CharField(label=_('Username'), source='full_username', read_only=True)

    class Meta:
        model = Account
        fields = [
            'id', 'name', 'username', 'secret_type',
            'secret', 'su_from', 'privileged'
        ]

    @staticmethod
    def get_su_from(account) -> dict:
        if not hasattr(account, 'asset'):
            return {}
        su_enabled = account.asset.platform.su_enabled
        su_from = account.su_from
        if not su_from or not su_enabled:
            return
        return _SimpleAccountSerializer(su_from).data


class _ConnectionTokenGatewaySerializer(serializers.ModelSerializer):
    account = _SimpleAccountSerializer(
        required=False, source='select_account', read_only=True
    )
    protocols = AssetProtocolsSerializer(many=True, required=False, label=_('Protocols'))

    class Meta:
        model = Gateway
        fields = [
            'id', 'name', 'address', 'protocols', 'account'
        ]


class _ConnectionTokenDataMaskingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataMaskingRule
        fields = ['id', 'name', 'fields_pattern',
                  'masking_method', 'mask_pattern',
                  'is_active', 'priority']


class _ConnectionTokenCommandFilterACLSerializer(serializers.ModelSerializer):
    command_groups = ObjectRelatedField(
        many=True, required=False, queryset=CommandGroup.objects,
        attrs=('id', 'name', 'type', 'content', 'ignore_case', 'pattern'),
        label=_('Command group')
    )
    reviewers = ObjectRelatedField(
        many=True, queryset=User.objects, label=_("Reviewers"), required=False
    )

    class Meta:
        model = CommandFilterACL
        fields = [
            'id', 'name', 'command_groups', 'action',
            'reviewers', 'priority', 'is_active'
        ]


class _ConnectionTokenPlatformSerializer(PlatformSerializer):
    class Meta(PlatformSerializer.Meta):
        model = Platform
        fields = [field for field in PlatformSerializer.Meta.fields
                  if field not in PlatformSerializer.Meta.fields_m2m]

    def get_field_names(self, declared_fields, info):
        names = super().get_field_names(declared_fields, info)
        names = [n for n in names if n not in ['automation']]
        return names


class _ConnectionTokenConnectMethodSerializer(serializers.Serializer):
    name = serializers.CharField(label=_('Name'))
    protocol = serializers.CharField(label=_('Protocol'))
    os = serializers.CharField(label=_('OS'))
    is_builtin = serializers.BooleanField(label=_('Is builtin'))
    is_active = serializers.BooleanField(label=_('Is active'))
    platform = _ConnectionTokenPlatformSerializer(label=_('Platform'))
    action = ActionChoicesField(label=_('Action'))
    options = serializers.JSONField(label=_('Options'))


class _ConnectTokenConnectMethodSerializer(serializers.Serializer):
    label = serializers.CharField(label=_('Label'))
    value = serializers.CharField(label=_('Value'))
    type = serializers.CharField(label=_('Type'))
    component = serializers.CharField(label=_('Component'))


class ConnectionTokenSecretSerializer(OrgResourceModelSerializerMixin):
    user = _ConnectionTokenUserSerializer(read_only=True)
    asset = _ConnectionTokenAssetSerializer(read_only=True)
    account = _ConnectionTokenAccountSerializer(read_only=True, source='account_object')
    gateway = serializers.SerializerMethodField()
    domain = serializers.SerializerMethodField()
    platform = _ConnectionTokenPlatformSerializer(read_only=True)
    zone = ObjectRelatedField(queryset=Zone.objects, required=False, label=_('Domain'))
    command_filter_acls = _ConnectionTokenCommandFilterACLSerializer(read_only=True, many=True)
    data_masking_rules = _ConnectionTokenDataMaskingRuleSerializer(read_only=True, many=True)
    expire_now = serializers.BooleanField(label=_('Expired now'), write_only=True, default=True)
    connect_method = _ConnectTokenConnectMethodSerializer(read_only=True, source='connect_method_object')
    connect_options = serializers.JSONField(read_only=True)
    actions = ActionChoicesField()
    expire_at = serializers.IntegerField()

    class Meta:
        model = ConnectionToken
        fields = [
            'id', 'value', 'user', 'asset', 'account',
            'platform', 'command_filter_acls', 'data_masking_rules', 'protocol',
            'zone', 'gateway', 'domain', 'actions', 'expire_at',
            'from_ticket', 'expire_now', 'connect_method',
            'connect_options', 'face_monitor_token'
        ]
        extra_kwargs = {
            'face_monitor_token': {'read_only': True},
            'value': {'read_only': True},
        }

    def get_gateway(self, instance):
        endpoint = instance.endpoint
        is_web = instance.connect_method in WebMethod.values
        has_endpoint = bool(endpoint and not endpoint.is_default() and endpoint.host)
        need_endpoint_gateway = (
            not is_web and instance.connect_method not in NO_ENDPOINT_GATEWAY_METHODS
        )

        # koko 承接的连接（SSH 命令行 / SSH 客户端与向导）落在入口 KoKo：先经伪网关
        # 隧道到端点所在区域，再由区域 KoKo 走真实网关（真实网关在 domain 字段下发）。
        # 因此该场景伪网关优先于真实网关，引导入口 KoKo 隧道到区域 KoKo。
        if need_endpoint_gateway and has_endpoint:
            return self._endpoint_gateway(endpoint, instance)
        if instance.gateway:
            return _ConnectionTokenGatewaySerializer(instance.gateway).data
        # 不再注入伪网关的情况：
        # - Web 连接（web_cli/web_sftp/web_gui）：入口 nginx 已按端点把连接路由到
        #   对应区域节点的 KoKo，该 KoKo 可直连资产，无需再注入伪网关多做一次转发
        # - 非 koko 消费者（见 NO_ENDPOINT_GATEWAY_METHODS）：magnus 的 DB 客户端按
        #   端点端口直连区域 magnus；razor / nec 的 RDP / VNC 客户端直连端点的
        #   razor / nec 端口。给它们下发伪网关会被拿去连区域 koko 并被拒（token 不是
        #   ssh 协议），表现为连上即断开
        # 都回到「有真实网关用真实网关，没有就不注入」的逻辑。
        return None

    @staticmethod
    def _endpoint_gateway(endpoint, instance):
        return {
            'id': str(endpoint.id),
            'name': f'endpoint-{endpoint.name}',
            'address': endpoint.host,
            'protocols': [{'name': 'ssh', 'port': endpoint.ssh_port}],
            'account': {
                'name': '@TOKEN',
                'username': f'JMS-{instance.value}',
                'secret_type': {'value': 'password', 'label': 'Password'},
                'secret': instance.value,
            },
        }

    def get_domain(self, instance):
        """真实网关（Zone 选中的网关）下发给区域 KoKo，供 SSH 命令行两级跳板
        的最后一段（区域 KoKo → 真实网关 → 目标资产）使用。复用 SDK 已有的
        ConnectToken.Domain 结构，无需改动 SDK。"""
        zone = instance.zone
        if not zone:
            return None
        gateways = []
        if instance.gateway:
            gateways.append(_ConnectionTokenGatewaySerializer(instance.gateway).data)
        return {'id': str(zone.id), 'name': zone.name, 'gateways': gateways}


class ConnectTokenAppletOptionSerializer(serializers.Serializer):
    id = serializers.CharField(label=_('ID'))
    applet = ObjectRelatedField(read_only=True)
    host = _ConnectionTokenAssetSerializer(read_only=True)
    account = _ConnectionTokenAccountSerializer(read_only=True)
    gateway = _ConnectionTokenGatewaySerializer(read_only=True)
    platform = _ConnectionTokenPlatformSerializer(read_only=True)
    remote_app_option = serializers.JSONField(read_only=True)


class ConnectTokenVirtualAppOptionSerializer(serializers.Serializer):
    name = serializers.CharField(label=_('Name'))
    image_name = serializers.CharField(label=_('Image name'))
    image_port = serializers.IntegerField(label=_('Image port'))
    image_protocol = serializers.CharField(label=_('Image protocol'))
