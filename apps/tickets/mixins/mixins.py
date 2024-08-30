# -*- coding: utf-8 -*-
#
from tickets.models import Ticket


class TicketQuerysetMixin:
    def get_queryset(self):
        queryset = Ticket.objects.all()
        return queryset
