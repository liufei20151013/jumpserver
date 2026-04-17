# -*- coding: utf-8 -*-
#
from django.db import models
from django.utils.translation import gettext_lazy as _

from labels.mixins import LabeledMixin

__all__ = ['DltAccount']

class DltAccount(LabeledMixin, models.Model):
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    cn = models.CharField(max_length=32, verbose_name=_('Name'))
    uid = models.CharField(max_length=32, verbose_name=_('UID'))
    org = models.CharField(max_length=32, verbose_name=_('Organization'))
    org_full_name = models.CharField(max_length=128, verbose_name=_('Organization Name'))
    email = models.CharField(max_length=32, verbose_name=_('Email'))
    mobile = models.CharField(max_length=32, verbose_name=_('Mobile'))
    status = models.CharField(max_length=2, default='0', verbose_name=_('Status'))
    action_type = models.CharField(max_length=10, verbose_name=_('Action Type'))
    date_updated = models.DateTimeField(auto_now=True, verbose_name=_('Date updated'))

    class Meta:
        db_table = 'dlt_account'
        verbose_name = _("登录通应用用户信息")

    def __str__(self):
        return (
            f"DltAccount(id={self.id}, cn={self.cn}, uid={self.uid}, org={self.org}, "
            f"org_full_name={self.org_full_name}, email={self.email}, mobile={self.mobile}, "
            f"status={self.status}, action_type={self.action_type}, date_updated={self.date_updated})"
        )
