import json

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.generics import RetrieveDestroyAPIView
from django.utils.translation import gettext_lazy as _

from audits.handler import create_or_update_operate_log
from common.utils import get_logger, response_message
from orgs.utils import tmp_to_root_org, tmp_to_org
from ..const import TicketAction, TicketState
from ..mixins.mixins import TicketQuerysetMixin
from ..models import Ticket, TicketStep, TicketAssignee, Comment
from users.models import User
from ..models.ticket.general import StatusMixin
from ..serializers import SuperTicketSerializer, TicketApproveSerializer

logger = get_logger(__name__)
__all__ = ['SuperTicketStatusAPI', 'ApproveTicketAPI']


class SuperTicketStatusAPI(RetrieveDestroyAPIView):
    serializer_class = SuperTicketSerializer
    rbac_perms = {
        'GET': 'tickets.view_superticket',
        'DELETE': 'tickets.change_superticket'
    }

    def get_queryset(self):
        with tmp_to_root_org():
            return Ticket.objects.all()

    def perform_destroy(self, instance):
        instance.close()


class ApproveTicketAPI(TicketQuerysetMixin, StatusMixin, generics.CreateAPIView):
    serializer_class = TicketApproveSerializer

    def create(self, request, *args, **kwargs):
        try:
            data = request.data
            logger.info("Approve ticket, request data: {}".format(json.dumps(data)))
            tickets = Ticket.objects.filter(serial_num=data['requestId'], state=TicketState.pending)
            if tickets.exists():
                ticket = tickets.first()
                users = User.objects.filter(username=data['approver'], is_active=True)
                if not users.exists():
                    return Response(response_message('failed', '审批人不存在或审批人账号已被禁用！审批人:' + data['approver']))

                user = users.first()
                ticketSteps = TicketStep.objects.filter(ticket=ticket, state=TicketState.pending)
                ticketAssignees = TicketAssignee.objects.filter(assignee=user, step=ticketSteps.first())
                if not ticketAssignees.exists():
                    return Response(response_message('failed', '审批人没有工单审批权限！审批人:' + data['approver']))

                self.kwargs.__setitem__('pk', ticket.id)
                instance = self.get_object()
                if data['approveResult'] == 0:
                    serializer = self.get_serializer(instance, data=ticket.rel_snapshot, partial=False)
                    with tmp_to_root_org():
                        serializer.is_valid(raise_exception=True)
                        instance = serializer.save()
                    instance.approve(processor=user)
                    self._record_operate_log(ticket, TicketAction.approve)
                else:
                    instance.reject(processor=user)
                    self._record_operate_log(ticket, TicketAction.reject)

                if len(data['opinion']) > 0:
                    comments = Comment.objects.filter(user=user, ticket=ticket).order_by('-date_created')
                    if comments.exists():
                        comment = comments.first()
                        comment.body = '{}  审批意见：{}'.format(comment.body, data['opinion'])
                        comment.save()
            else:
                return Response(response_message('failed', '工单不存在或已审批！requestId:' + data['requestId']))

        except Exception as e:
            logger.error('工单审批失败：{}'.format(e))
            return Response(response_message('failed', e))

        return Response(response_message('success', '审批结束！'))

    @staticmethod
    def _record_operate_log(ticket, action):
        with tmp_to_org(ticket.org_id):
            after = {
                'ID': str(ticket.id),
                str(_('Name')): ticket.title,
                str(_('Applicant')): str(ticket.applicant),
            }
            object_name = ticket._meta.object_name
            resource_type = ticket._meta.verbose_name
            create_or_update_operate_log(
                action, resource_type, resource=ticket,
                after=after, object_name=object_name
            )
