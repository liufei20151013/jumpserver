# ~*~ coding: utf-8 ~*~
from celery import shared_task
from django.utils.translation import gettext_noop, gettext_lazy as _

from assets.const import AutomationTypes
from common.utils import get_logger
from orgs.utils import tmp_to_org, current_org
from .common import quickstart_automation

logger = get_logger(__file__)

__all__ = [
    'test_assets_connectivity_task',
    'test_assets_connectivity_manual',
    'test_node_assets_connectivity_manual',
]


@shared_task(
    verbose_name=_('Test assets connectivity'),
    queue='ansible',
    activity_callback=lambda self, asset_ids, org_id, *args, **kwargs: (asset_ids, org_id),
    description=_(
        "When clicking 'Test Asset Connectivity' in 'Asset Details - Basic Settings' this task will be executed"
    )
)
def test_assets_connectivity_task(asset_ids, org_id, task_name=None):
    from assets.models import PingAutomation
    if task_name is None:
        task_name = gettext_noop("Test assets connectivity")

    task_name = PingAutomation.generate_unique_name(task_name)
    task_snapshot = {'assets': asset_ids}
    with tmp_to_org(org_id):
        quickstart_automation(task_name, AutomationTypes.ping, task_snapshot)


def test_assets_connectivity_manual(assets):
    from common.utils.endpoint_routing import dispatch_task_to_endpoints
    task_name = gettext_noop("Test assets connectivity ")
    asset_ids = [str(i.id) for i in assets]
    org_id = str(current_org.id)
    return dispatch_task_to_endpoints(
        test_assets_connectivity_task, asset_ids,
        extra_args=[org_id, task_name],
        log_sync=True  # 连通性测试：副节点增量同步日志到主节点
    )


def test_node_assets_connectivity_manual(node):
    from common.utils.endpoint_routing import dispatch_task_to_endpoints
    task_name = gettext_noop("Test if the assets under the node are connectable ")
    asset_ids = node.get_all_asset_ids()
    asset_ids = [str(i) for i in asset_ids]
    org_id = str(current_org.id)
    return dispatch_task_to_endpoints(
        test_assets_connectivity_task, asset_ids,
        extra_args=[org_id, task_name],
        log_sync=True  # 连通性测试：副节点增量同步日志到主节点
    )
