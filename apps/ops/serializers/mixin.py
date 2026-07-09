from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from common.serializers.fields import LabeledChoiceField
from ..const import Scope


class ScopeSerializerMixin(serializers.Serializer):
    scope = LabeledChoiceField(
        choices=Scope.choices, default=Scope.private, label=_("Scope")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if not request or not hasattr(request, "user"):
            return

        is_superuser = request.user.is_superuser
        if not is_superuser:
            self.fields["scope"].choices = [(Scope.private, Scope.private)]
