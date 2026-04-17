from __future__ import unicode_literals

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DltsConfig(AppConfig):
    name = 'dlt'
    verbose_name = _('App Dlts')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def ready(self):
        super().ready()
