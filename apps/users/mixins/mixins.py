# -*- coding: utf-8 -*-
#
from users.models import UserGroup


class UserGroupQuerysetMixin:
    def get_queryset(self):
        queryset = UserGroup.objects.all()
        return queryset
