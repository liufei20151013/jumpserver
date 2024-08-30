from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from .models import Organization
from .utils import get_current_org
from django.utils.translation import gettext_lazy as _


class ResourceStatisticsSerializer(serializers.Serializer):
    users_amount = serializers.IntegerField(required=False)
    groups_amount = serializers.IntegerField(required=False)

    assets_amount = serializers.IntegerField(required=False)
    nodes_amount = serializers.IntegerField(required=False)
    domains_amount = serializers.IntegerField(required=False)
    gateways_amount = serializers.IntegerField(required=False)

    asset_perms_amount = serializers.IntegerField(required=False)


class OrgSerializer(ModelSerializer):
    resource_statistics = ResourceStatisticsSerializer(source='resource_statistics_cache', read_only=True)
    org_code = serializers.CharField(max_length=64, required=False, allow_blank=True, label=_('Organization Code'))

    class Meta:
        model = Organization
        fields_mini = ['id', 'name']
        fields_small = fields_mini + [
            'resource_statistics',
            'is_default', 'is_root', 'internal',
            'date_created', 'created_by',
            'comment', 'created_by', 'org_code',
        ]

        fields_m2m = []
        fields = fields_small + fields_m2m
        read_only_fields = ['created_by', 'date_created']


class CurrentOrgSerializer(ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'is_default', 'is_root', 'comment']


class CurrentOrgDefault:
    requires_context = False

    def __call__(self, *args):
        return get_current_org()

    def __repr__(self):
        return '%s()' % self.__class__.__name__


class AddOrgSerializer(ModelSerializer):
    class Meta:
        model = Organization
        fields = ['name']
