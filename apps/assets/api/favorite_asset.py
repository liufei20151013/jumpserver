# -*- coding: utf-8 -*-
#
from rest_framework_bulk.generics import BulkModelViewSet

from common.permissions import IsValidUser
from orgs.utils import tmp_to_root_org
from ..const import Category
from ..models import FavoriteAsset, Platform, Asset
from ..serializers import FavoriteAssetSerializer

__all__ = ['FavoriteAssetViewSet', 'FavoriteAssetNoWebViewSet']


class FavoriteAssetViewSet(BulkModelViewSet):
    serializer_class = FavoriteAssetSerializer
    permission_classes = (IsValidUser,)
    filterset_fields = ['asset']
    page_no_limit = True

    def dispatch(self, request, *args, **kwargs):
        with tmp_to_root_org():
            return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = FavoriteAsset.objects.filter(user=self.request.user)
        return queryset

    def allow_bulk_destroy(self, qs, filtered):
        return filtered.count() == 1

class FavoriteAssetNoWebViewSet(BulkModelViewSet):
    serializer_class = FavoriteAssetSerializer
    permission_classes = (IsValidUser,)
    filterset_fields = ['asset']
    page_no_limit = True

    def dispatch(self, request, *args, **kwargs):
        with tmp_to_root_org():
            return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        platforms = Platform.objects.filter(category=Category.WEB.value)
        assets = Asset.objects.exclude(platform__in=platforms).values_list('id', flat=True)
        queryset = FavoriteAsset.objects.filter(user=self.request.user, asset__in=assets)
        return queryset

    def allow_bulk_destroy(self, qs, filtered):
        return filtered.count() == 1
