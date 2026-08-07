from .celery_base import CeleryBaseService

__all__ = ['CeleryAnsibleService']


class CeleryAnsibleService(CeleryBaseService):

    def __init__(self, **kwargs):
        # 自动检测本节点对应的端点队列
        # 优先使用环境变量 JMS_ENDPOINT_NAME 显式指定的端点；
        # 未配置时通过本机 IP / DNS 匹配 Endpoint.host。
        # 未匹配到时回退到默认的 'ansible' 队列
        try:
            from common.utils.endpoint_routing import detect_local_queue
            queue = detect_local_queue()
        except Exception:
            queue = 'ansible'
        kwargs['queue'] = queue
        super().__init__(**kwargs)

    def start_other(self):
        from terminal.startup import CeleryTerminal
        celery_terminal = CeleryTerminal()
        celery_terminal.start_heartbeat_thread()

