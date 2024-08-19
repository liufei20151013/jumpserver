# ~*~ coding: utf-8 ~*~
from common.utils import get_logger
from orgs.mixins.api import OrgBulkModelViewSet
from rbac.permissions import RBACPermission
from .. import serializers
from ..models import FavoriteNode

logger = get_logger(__file__)
__all__ = ['FavoriteNodeViewSet']


class FavoriteNodeViewSet(OrgBulkModelViewSet):
    model = FavoriteNode
    permission_classes = (RBACPermission,)
    filterset_fields = ("name",)
    search_fields = filterset_fields
    ordering = ('name',)
    serializer_class = serializers.FavoriteNodeSerializer

    def get_queryset(self):
        queryset = FavoriteNode.objects.filter(user=self.request.user)
        return queryset

    def get_serializer_class(self):
        return super().get_serializer_class()
