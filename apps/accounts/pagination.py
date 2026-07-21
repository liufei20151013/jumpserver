from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from typing import Optional

from common.utils import get_logger

logger = get_logger(__name__)


class AccountPaginationBase(LimitOffsetPagination):

    _request: Optional[Request] = None
    _view = None

    def init_attrs(self, request: Request, view=None) -> None:
        self._request = request
        self._view = view

    def paginate_queryset(self, queryset, request: Request, view=None):
        self.init_attrs(request, view)
        return super().paginate_queryset(queryset, request, view)

class AllAccountPagination(AccountPaginationBase):
    def get_count(self, queryset) -> int:
        if not queryset:
            return 0
        return queryset.distinct().count()
