# -*- coding: utf-8 -*-
#
import json
from datetime import datetime

import requests
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.conf import settings

from accounts.models import Account
from assets.models import Asset
from audits.handler import create_or_update_operate_log
from common.api import CommonApiMixin
from common.const.http import POST, PUT, PATCH
from common.utils import get_logger
from orgs.utils import tmp_to_root_org, tmp_to_org
from rbac.permissions import RBACPermission
from tickets import filters
from tickets import serializers
from tickets.models import (
    Ticket, ApplyAssetTicket, ApplyLoginTicket,
    ApplyLoginAssetTicket, ApplyCommandTicket, ApprovalRule
)
from tickets.permissions.ticket import IsAssignee, IsApplicant
from ..const import TicketAction, TicketApprovalStrategy

logger = get_logger(__name__)
__all__ = [
    'TicketViewSet', 'ApplyAssetTicketViewSet',
    'ApplyLoginTicketViewSet', 'ApplyLoginAssetTicketViewSet',
    'ApplyCommandTicketViewSet'
]


class TicketViewSet(CommonApiMixin, viewsets.ModelViewSet):
    serializer_class = serializers.TicketSerializer
    serializer_classes = {
        'approve': serializers.TicketApproveSerializer
    }
    model = Ticket
    perm_model = Ticket
    filterset_class = filters.TicketFilter
    search_fields = [
        'title', 'type', 'status'
    ]
    ordering = ('-date_created',)
    rbac_perms = {
        'open': 'tickets.view_ticket',
    }

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        with tmp_to_root_org():
            serializer = self.get_serializer(instance)
            data = serializer.data
        return Response(data)

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed(self.action)

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed(self.action)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(self.action)

    def ticket_not_allowed(self):
        if self.model == Ticket:
            raise MethodNotAllowed(self.action)

    def get_queryset(self):
        with tmp_to_root_org():
            queryset = self.model.get_user_related_tickets(self.request.user)
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save()
        instance.save(update_fields=['applicant'])
        instance.open()

    @action(detail=False, methods=[POST], permission_classes=[RBACPermission, ])
    def open(self, request, *args, **kwargs):
        with tmp_to_root_org():
            enabled = settings.ITOP_ENABLED
            if self.basename == 'apply-asset-ticket' and enabled:
                enabled = settings.ITOP_ENABLED
                if enabled:
                    try:
                        data = request.data
                        apply_assets = data.get('apply_assets', None)
                        if not apply_assets:
                            return Response({'error': '请选择资产！'}, status=400)

                        apply_accounts = data.get('apply_accounts', [])
                        if len(apply_accounts) <= 1:
                            return Response({'error': '未指定账号！'}, status=400)

                        # 查询自定义超管账号审批人
                        approval_rule = ApprovalRule.objects.filter(strategy=TicketApprovalStrategy.custom_user).first()
                        top_approver = approval_rule.assignees.first().username

                        asset_approvers = {}
                        asset_usernames = {}
                        super_account_usernames = ['root', 'administrator', 'admin']

                        assets = Asset.objects.filter(id__in=apply_assets)
                        for asset in assets:
                            accounts = Account.objects.filter(asset=asset).values_list('username', flat=True)
                            apply_account_usernames = list(set(accounts) & set(apply_accounts))
                            apply_account_usernames = self.sort_list(apply_account_usernames)

                            asset_id = str(asset.id)
                            asset_usernames[asset_id] = apply_account_usernames if len(apply_account_usernames) > 0 else ['-']

                            # 非特权账号则由资产负责人审批
                            intersection_account_usernames = list(set(apply_account_usernames) & set(super_account_usernames))
                            if len(intersection_account_usernames) == 0:
                                director = asset.director.username
                                if director:
                                    approver = director
                            else:
                                approver = top_approver

                            if approver in asset_approvers:
                                asset_approvers[approver].append(asset_id)
                            else:
                                asset_approvers[approver] = [asset_id]

                        for key, value in asset_approvers.items():
                            request.data['apply_assets'] = value
                            request.data['approver'] = key
                            response = super().create(request, *args, **kwargs)

                            # 创建 ITOP 审批流程
                            ticket_id = response.data['id']
                            ticket = Ticket.objects.get(pk=ticket_id)
                            trackId = ''.join(ticket_id.split('-'))
                            itop_url = '{}/esb/comm/itop_formdata/api'.format(settings.ITOP_HOST)
                            # 参数要用双引号，ITOP 那边是 java 开发的，用单引号则 json 字符串转换会有问题
                            headers = {
                                "Content-Type": "application/json",
                                "requestId": ticket_id,
                                "trackId": trackId,
                                "sourceSystem": "IAM",
                                "serviceName": "S_XXX_ITOP_NewRequisition_S",
                            }
                            logger.info('ITOP create ticket process, headers: {}'.format(headers))

                            description = '申请资产详细：\n资产名称/资产地址/申请账号名\n'
                            assets = Asset.objects.filter(id__in=request.data['apply_assets'])
                            for asset in assets:
                                description += "{}/{}/{}\n".format(asset.name, asset.address,
                                                                   ", ".join(asset_usernames[str(asset.id)]))
                            description += "申请备注：\n{}".format(ticket.comment)
                            logger.info('ITOP create ticket process, description: {}'.format(description))

                            data = {
                                "operation": "core/create",
                                "class": "UserRequestInterface",
                                "comment": "Synchronization from blah...",
                                "output_fields": "id, friendlyname",
                                "fields": {
                                    "apply_id": ticket.serial_num,
                                    "title": ticket.title,
                                    "description": "{}",
                                    "apply_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "approver": request.data['approver']
                                }
                            }
                            logger.info('ITOP create ticket process, data: {}'.format(json.dumps(data).replace("{}", description)))
                            result = requests.post(itop_url, headers=headers, data=json.dumps(data), verify=False)
                            logger.info('ITOP create ticket process, result: {}'.format(json.loads(result.text)))
                            if result.status_code != 200:
                                content = json.loads(result.text)
                                logger.error('ITOP create ticket process failed, code: {}, message: {}'
                                             .format(content['code'], content['message']))

                        return Response({'success': '创建成功！'}, status=200)
                    except Exception as e:
                        logger.error('ITOP create ticket process failed, error: {}'.format(e))
                        raise e
            else:
                return super().create(request, *args, **kwargs)

    def sort_list(self, lst):
        def custom_sort(item):
            # 提取英文部分并转换为小写
            english_part = ''.join([char for char in item if char.isalpha() and not char.isascii()]).lower()
            return english_part

        return sorted(lst, key=custom_sort)


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

    @action(detail=True, methods=[PUT, PATCH], permission_classes=[IsAssignee, ])
    def approve(self, request, *args, **kwargs):
        self.ticket_not_allowed()

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        with tmp_to_root_org():
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
        instance.approve(processor=request.user)
        self._record_operate_log(instance, TicketAction.approve)
        return Response('ok')

    @action(detail=True, methods=[PUT], permission_classes=[IsAssignee, ])
    def reject(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.reject(processor=request.user)
        self._record_operate_log(instance, TicketAction.reject)
        return Response('ok')

    @action(detail=True, methods=[PUT], permission_classes=[IsAssignee | IsApplicant, ])
    def close(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.close()
        self._record_operate_log(instance, TicketAction.close)
        return Response('ok')

    @action(detail=False, methods=[PUT], permission_classes=[IsAuthenticated, ])
    def bulk(self, request, *args, **kwargs):
        self.ticket_not_allowed()

        allow_action = ('approve', 'reject')
        action_ = request.query_params.get('action')
        if action_ not in allow_action:
            msg = _("The parameter 'action' must be [{}]").format(','.join(allow_action))
            return Response({'error': msg}, status=400)

        ticket_ids = request.data.get('tickets', [])
        queryset = self.get_queryset().filter(state='pending').filter(id__in=ticket_ids)
        for obj in queryset:
            if not obj.has_current_assignee(request.user):
                return Response(
                    {'error': f"{_('User does not have permission')}: {obj}"}, status=400
                )
            handler = getattr(obj, action_)
            handler(processor=request.user)
        return Response('ok')


class ApplyAssetTicketViewSet(TicketViewSet):
    model = ApplyAssetTicket
    filterset_class = filters.ApplyAssetTicketFilter
    serializer_class = serializers.ApplyAssetSerializer
    serializer_classes = {
        'open': serializers.ApplyAssetSerializer,
        'approve': serializers.ApproveAssetSerializer
    }


class ApplyLoginTicketViewSet(TicketViewSet):
    model = ApplyLoginTicket
    filterset_class = filters.ApplyLoginTicketFilter
    serializer_class = serializers.LoginReviewSerializer


class ApplyLoginAssetTicketViewSet(TicketViewSet):
    model = ApplyLoginAssetTicket
    filterset_class = filters.ApplyLoginAssetTicketFilter
    serializer_class = serializers.LoginAssetReviewSerializer


class ApplyCommandTicketViewSet(TicketViewSet):
    model = ApplyCommandTicket
    filterset_class = filters.ApplyCommandTicketFilter
    serializer_class = serializers.ApplyCommandReviewSerializer
