# -*- coding: utf-8 -*-
#
import itertools
from collections import defaultdict

from django.conf import settings
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from assets.const import Protocol
from .const import TerminalType


class WebMethod(TextChoices):
    web_gui = 'web_gui', 'Web GUI'
    web_cli = 'web_cli', 'Web CLI'
    web_sftp = 'web_sftp', 'Web SFTP'

    @classmethod
    def get_spec_methods(cls):
        methods = {
            Protocol.sftp: [cls.web_sftp]
        }
        return methods


class NativeClient(TextChoices):
    # Koko
    ssh_client = 'ssh_client', _('SSH Client')
    ssh_guide = 'ssh_guide', _('SSH Guide')
    sftp_client = 'sftp_client', _('SFTP Client')
    # Magnus
    db_guide = 'db_guide', _('DB Guide')
    db_client = 'db_client', _('DB Client')
    # Razor
    mstsc = 'mstsc', _('Remote Desktop')
    rdp_guide = 'rdp_guide', _('RDP Guide')
    # NEC
    vnc_client = 'vnc_client', _('VNC Client')
    vnc_guide = 'vnc_guide', _('VNC Guide')

    @classmethod
    def get_native_clients(cls):
        # native client 关注的是 endpoint 的 protocol,
        # 比如 telnet mysql, koko 都支持，到那时暴露的是 ssh 协议
        clients = {
            Protocol.ssh: [cls.ssh_client, cls.ssh_guide],
            Protocol.sftp: [cls.sftp_client],
            Protocol.rdp: [cls.mstsc],
            Protocol.mysql: [cls.db_client, cls.db_guide],
            Protocol.mariadb: [cls.db_client, cls.db_guide],
            Protocol.redis: [cls.db_client, cls.db_guide],
            Protocol.mongodb: [cls.db_client, cls.db_guide],
            Protocol.oracle: [cls.db_client, cls.db_guide],
            Protocol.postgresql: [cls.db_client, cls.db_guide],
            Protocol.sqlserver: [cls.db_client, cls.db_guide],
            Protocol.vnc: [cls.vnc_client, cls.vnc_guide],
        }
        return clients

    @classmethod
    def get_target_protocol(cls, name, os):
        for protocol, clients in cls.get_native_clients().items():
            if isinstance(clients, dict):
                if os == 'all':
                    clients = list(itertools.chain(*clients.values()))
                else:
                    clients = clients.get(os) or clients.get('default')
            if name in clients:
                return protocol
        return None

    @classmethod
    def xpack_methods(cls):
        return [cls.mstsc, cls.db_client, cls.vnc_guide]

    @classmethod
    def get_methods(cls, os='windows'):
        clients_map = cls.get_native_clients()
        methods = defaultdict(list)
        xpack_protocols = Protocol.xpack_protocols()

        for protocol, _clients in clients_map.items():
            if not settings.XPACK_LICENSE_IS_VALID and protocol in xpack_protocols:
                continue
            if isinstance(_clients, dict):
                if os == 'all':
                    _clients = list(itertools.chain(*_clients.values()))
                else:
                    _clients = _clients.get(os, _clients['default'])
            for client in _clients:
                if not settings.XPACK_LICENSE_IS_VALID and client in cls.xpack_methods():
                    continue
                methods[protocol].append({
                    'value': client.value,
                    'label': client.label,
                    'type': 'native',
                })
        return methods


# 不注入端点伪网关（Endpoint Gateway）的连接方式。
#
# 端点伪网关只服务于 koko 的 SSH 系代理：koko 以 JMS-<token> 身份 dial 伪网关
# （= 区域 koko 的 ssh 端口）隧道到端点所在区域，再由区域 koko 连资产。因此只有
# koko 承接的连接方式能消费它；其余消费者拿到伪网关会直接失败：
#
# - magnus（db_client / db_guide）：magnus 不消费伪网关，它需要 Zone 下发的
#   domain 网关（真实网关），拿不到时报 `启动数据库网关失败 no available domain`，
#   客户端侧表现为 ORA-17410 / `unexpected pre-login response` 之类的协议层错误。
# - razor（mstsc / rdp_guide）/ nec（vnc_client / vnc_guide）：它们会尝试用伪网关
#   建立 SSH 隧道，但 token 协议不是 ssh，区域 koko 按
#   `not ssh asset connection token` 拒绝，客户端表现为连上即秒断开。
#
# 未列入的连接方式保持伪网关注入行为不变（koko 命令行的 ssh/telnet/sftp、SSH
# 客户端/向导、koko 自建令牌），SSH 命令行两级跳板不受影响。
NO_ENDPOINT_GATEWAY_METHODS = {
    # magnus DB 客户端
    'db_client', 'db_guide',
    # razor RDP 客户端 / nec VNC 客户端
    'mstsc', 'rdp_guide', 'vnc_client', 'vnc_guide',
}


class AppletMethod:
    @classmethod
    def get_methods(cls):
        from .models import Applet, AppletHost

        methods = defaultdict(list)
        has_applet_hosts = AppletHost.objects.filter(is_active=True).exists()
        if not has_applet_hosts:
            return methods
        applets = Applet.objects.filter(is_active=True)
        for applet in applets:
            for protocol in applet.protocols:
                methods[protocol].append({
                    'value': applet.name,
                    'label': applet.display_name,
                    'type': 'applet',
                    'icon': applet.icon,
                    'disabled': not applet.is_active,
                })
        return methods


class VirtualAppMethod:

    @classmethod
    def get_methods(cls):
        from .models import VirtualApp
        methods = defaultdict(list)
        if not getattr(settings, 'VIRTUAL_APP_ENABLED'):
            return methods
        virtual_apps = VirtualApp.objects.filter(is_active=True)
        for virtual_app in virtual_apps:
            for protocol in virtual_app.protocols:
                methods[protocol].append({
                    'value': virtual_app.name,
                    'label': virtual_app.name,
                    'type': 'virtual_app',
                    'disabled': not virtual_app.is_active,
                })
        return methods


class ConnectMethodUtil:
    _all_methods = {}

    @classmethod
    def components(cls):
        protocols = {
            TerminalType.koko: {
                'web_methods': [WebMethod.web_cli],
                'listen': [Protocol.http, Protocol.ssh, Protocol.sftp],
                'support': [
                    Protocol.ssh, Protocol.telnet, Protocol.sftp,
                    Protocol.redis, Protocol.mongodb,
                    Protocol.k8s, Protocol.clickhouse,

                    Protocol.mysql, Protocol.mariadb,
                    Protocol.sqlserver, Protocol.postgresql,
                    Protocol.oracle
                ],
                # 限制客户端的协议，比如 koko 虽然也支持 数据库的 ssh 连接，但是不再这里拉起
                # Listen协议: [Asset协议]
                'client_limits': {
                    Protocol.sftp: [Protocol.sftp],
                    Protocol.ssh: [Protocol.ssh, Protocol.telnet],
                },
                'match': 'm2m'
            },
            TerminalType.chen: {
                'web_methods': [WebMethod.web_gui],
                'listen': [Protocol.http],
                'support': [
                    Protocol.mysql, Protocol.postgresql,
                    Protocol.oracle, Protocol.sqlserver,
                    Protocol.mariadb, Protocol.db2,
                    Protocol.dameng
                ],
                'match': 'm2m'
            },
            TerminalType.lion: {
                'web_methods': [WebMethod.web_gui],
                'listen': [Protocol.http],
                'support': [Protocol.rdp, Protocol.vnc],
                'match': 'm2m'
            },
            TerminalType.magnus: {
                'web_methods': [],
                'listen': [],
                'support': [
                    Protocol.mysql, Protocol.postgresql,
                    Protocol.oracle, Protocol.mariadb,
                    Protocol.redis, Protocol.sqlserver,
                    Protocol.mongodb
                ],
                'match': 'map'
            },
            TerminalType.razor: {
                'web_methods': [],
                'listen': [Protocol.rdp],
                'support': [Protocol.rdp],
                'match': 'map'
            },
            TerminalType.kael: {
                'web_methods': [WebMethod.web_gui],
                'listen': [Protocol.http],
                'support': [Protocol.chatgpt],
                'match': 'm2m'
            },
            TerminalType.nec: {
                'web_methods': [],
                'listen': [Protocol.vnc],
                'support': [Protocol.vnc],
                'match': 'map'
            }
        }
        return protocols

    @classmethod
    def get_connect_method(cls, name, protocol, os='linux'):
        methods = cls.get_protocols_connect_methods(os)
        protocol_methods = methods.get(protocol, [])
        for method in protocol_methods:
            if method['value'] == name:
                return method
        return None

    @classmethod
    def refresh_methods(cls):
        cls._all_methods = {}

    @classmethod
    def get_filtered_protocols_connect_methods(cls, os):
        methods = dict(cls.get_protocols_connect_methods(os))
        methods = cls._filter_disable_components_connect_methods(methods)
        methods = cls._filter_disable_protocols_connect_methods(methods)
        return methods

    @classmethod
    def get_user_allowed_connect_methods(cls, os, user):
        from acls.models import ConnectMethodACL
        methods = cls.get_filtered_protocols_connect_methods(os)
        accept_methods = set(itertools.chain.from_iterable(
            ConnectMethodACL.get_user_acls(user)
            .filter(action=ConnectMethodACL.ActionChoices.accept)
            .values_list('connect_methods', flat=True)
        ))
        # 在禁用的基础上放行一些连接方法
        disabled_connect_methods = set(itertools.chain.from_iterable(
            ConnectMethodACL.get_user_acls(user)
            .filter(action=ConnectMethodACL.ActionChoices.reject)
            .values_list('connect_methods', flat=True)
        )) - accept_methods

        new_queryset = {}
        for protocol, methods in methods.items():
            new_queryset[protocol] = [x for x in methods if x['value'] not in disabled_connect_methods]
        return new_queryset

    @classmethod
    def _filter_disable_components_connect_methods(cls, methods):
        component_setting = {
            'razor': 'TERMINAL_RAZOR_ENABLED',
            'magnus': 'TERMINAL_MAGNUS_ENABLED',
        }
        disabled_component = [comp for comp, attr in component_setting.items() if
                              not (getattr(settings, attr) and settings.XPACK_LICENSE_IS_VALID)]
        if not disabled_component:
            return methods

        for protocol, ms in methods.items():
            filtered_methods = [m for m in ms if m['component'] not in disabled_component]
            methods[protocol] = filtered_methods
        return methods

    @classmethod
    def _filter_disable_protocols_connect_methods(cls, methods):
        # 过滤一些特殊的协议方式
        if not getattr(settings, 'TERMINAL_KOKO_SSH_ENABLED'):
            disable_ssh_client_protocols = [Protocol.ssh, Protocol.sftp, Protocol.telnet]
            for protocol in disable_ssh_client_protocols:
                methods[protocol] = [m for m in methods[protocol] if m['type'] != 'native']
        return methods

    @classmethod
    def get_protocols_connect_methods(cls, os='windows'):
        if cls._all_methods.get('os'):
            return cls._all_methods['os']

        methods = defaultdict(list)
        spec_web_methods = WebMethod.get_spec_methods()
        applet_methods = AppletMethod.get_methods()
        virtual_app_methods = VirtualAppMethod.get_methods()
        native_methods = NativeClient.get_methods(os=os)

        for component, component_protocol in cls.components().items():
            support = component_protocol['support']
            default_web_methods = component_protocol.get('web_methods', [])
            client_limits = component_protocol.get('client_limits', {})

            for asset_protocol in support:
                # Web 方式
                web_methods = spec_web_methods.get(asset_protocol, [])
                if not web_methods:
                    web_methods = default_web_methods
                methods[str(asset_protocol)].extend([
                    {
                        'component': component.value,
                        'type': 'web',
                        'endpoint_protocol': 'http',
                        'value': method.value,
                        'label': method.label,
                    }
                    for method in web_methods
                ])

                # 客户端方式
                if component_protocol['match'] == 'map':
                    listen = [asset_protocol]
                else:
                    listen = component_protocol['listen']

                for listen_protocol in listen:
                    limits = client_limits.get(listen_protocol, [])
                    if limits and asset_protocol not in limits:
                        continue
                    # Native method
                    client_methods = native_methods.get(listen_protocol, [])
                    methods[str(asset_protocol)].extend([
                        {
                            'component': component.value,
                            'type': 'native',
                            'endpoint_protocol': listen_protocol,
                            **method
                        }
                        for method in client_methods
                    ])

        # 远程应用方式，这个只有 tinker 提供，并且协议可能是自定义的
        for asset_protocol, applet_methods in applet_methods.items():
            for method in applet_methods:
                method['listen'] = 'rdp'
                method['component'] = TerminalType.tinker.value
            methods[asset_protocol].extend(applet_methods)

        # 虚拟应用方式，这个只有 panda 提供，并且协议可能是自定义的
        for protocol, virtual_app_methods in virtual_app_methods.items():
            for method in virtual_app_methods:
                method['listen'] = Protocol.http
                method['component'] = TerminalType.panda.value
            methods[protocol].extend(virtual_app_methods)

        cls._all_methods[os] = methods
        return methods
