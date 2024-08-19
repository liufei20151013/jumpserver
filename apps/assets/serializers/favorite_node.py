# -*- coding: utf-8 -*-
#
from rest_framework import serializers

from assets.models import FavoriteNode
from orgs.mixins.serializers import BulkOrgResourceModelSerializer

__all__ = ['FavoriteNodeSerializer']


class FavoriteNodeSerializer(BulkOrgResourceModelSerializer):

    user = serializers.HiddenField(
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        model = FavoriteNode
        fields_mini = ['id', 'name', 'user']
        fields_small = fields_mini + ['comment']
        read_only_fields = ['date_created']
        fields = fields_small + read_only_fields

