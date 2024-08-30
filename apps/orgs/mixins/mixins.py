# -*- coding: utf-8 -*-
#
from orgs.models import Organization


class OrgQuerysetMixin:
    def get_queryset(self):
        queryset = Organization.objects.all()
        return queryset
