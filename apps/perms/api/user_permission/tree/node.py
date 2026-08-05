from rest_framework.response import Response

from assets.api import SerializeToTreeNodeMixin
from assets.models import Asset
from common.utils import get_logger

from ..nodes import (
    UserAllPermedNodesApi,
    UserPermedNodeChildrenApi,
)

logger = get_logger(__name__)

__all__ = [
    'UserAllPermedNodesAsTreeApi',
    'UserPermedNodeChildrenAsTreeApi',
]


class NodeTreeMixin(SerializeToTreeNodeMixin):
    filter_queryset: callable
    get_queryset: callable

    # def list(self, request, *args, **kwargs):
    #     nodes = self.filter_queryset(self.get_queryset())
    #     data = self.serialize_nodes(nodes, with_asset_amount=True)
    #     return Response(data)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        nodes = self.filter_queryset(queryset)
        for node in nodes:
            if node.id == 'favorite':
                continue
            if node.level == 1:
                assets = Asset.objects.filter(org_id=node.org_id, is_active=True).distinct()
                node.assets_amount = len(assets)
            else:
                assets = node.assets.filter(is_active=True)
                node.assets_amount = len(assets)
        data = self.serialize_nodes(nodes, with_asset_amount=True)
        return Response(data)


class UserAllPermedNodesAsTreeApi(NodeTreeMixin, UserAllPermedNodesApi):
    """ 用户 '授权的节点' 作为树 """
    pass


class UserPermedNodeChildrenAsTreeApi(NodeTreeMixin, UserPermedNodeChildrenApi):
    """ 用户授权的节点下的子节点树 """
    pass


