from rest_framework import serializers

from dlt.models import DltAccount

__all__ = ['DltAccountSerializer']

class DltAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = DltAccount
        fields = [
            'id', 'cn', 'uid', 'org', 'org_full_name', 'email', 'mobile', 'status', 'action_type', 'date_updated'
        ]
