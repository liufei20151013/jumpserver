# -*- coding: utf-8 -*-
#
from django.db import models
from django.utils.translation import gettext_lazy as _

from common.utils import get_logger
from orgs.mixins.models import JMSOrgBaseModel

logger = get_logger(__file__)

__all__ = ['FavoriteNode']


class FavoriteNode(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("FavoriteNode")
        unique_together = ('org_id', 'name', 'user')
        ordering = ('name',)

    def __str__(self):
        return self.name
