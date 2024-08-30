from django.utils.translation import gettext as _

from assets.models import Asset, Node
from orgs.utils import tmp_to_org
from perms.models import AssetPermission
from tickets.models import ApplyAssetTicket
from .base import BaseHandler


class Handler(BaseHandler):
    ticket: ApplyAssetTicket

    def _on_step_approved(self, step):
        is_finished = super()._on_step_approved(step)
        if is_finished:
            self._create_asset_permission()

    def _create_asset_permission(self):
        org_id = self.ticket.org_id
        with tmp_to_org(org_id):
            asset_permission = AssetPermission.objects.filter(id=self.ticket.id).first()
            if asset_permission:
                return asset_permission

            try:
                apply_nodes = self.ticket.apply_nodes.all()
                apply_assets = self.ticket.apply_assets.all()
            except Exception as e:
                applyAssetTicket = self.ticket.applyassetticket
                rel_snapshot = applyAssetTicket.rel_snapshot

                apply_assets = []
                rel_apply_assets = rel_snapshot['apply_assets']
                if len(rel_apply_assets) > 0:
                    apply_assetnames = []
                    for apply_asset in rel_apply_assets:
                        asset_name = apply_asset.split('(')[0]
                        apply_assetnames.append(asset_name)
                    apply_assets = Asset.objects.filter(name__in=apply_assetnames)

                apply_nodes = []
                rel_apply_nodes = rel_snapshot['apply_nodes']
                if len(rel_apply_nodes) > 0:
                    apply_nodes = Node.objects.filter(full_value__in=rel_apply_nodes)

                self.ticket.apply_accounts = applyAssetTicket.apply_accounts
                self.ticket.apply_actions = applyAssetTicket.apply_actions
                self.ticket.apply_date_start = applyAssetTicket.apply_date_start
                self.ticket.apply_date_expired = applyAssetTicket.apply_date_expired
                self.ticket.apply_permission_name = applyAssetTicket.apply_permission_name

        apply_permission_name = self.ticket.apply_permission_name
        apply_actions = self.ticket.apply_actions
        apply_accounts = self.ticket.apply_accounts
        apply_date_start = self.ticket.apply_date_start
        apply_date_expired = self.ticket.apply_date_expired
        permission_created_by = '{}:{}'.format(
            str(self.ticket.__class__.__name__), str(self.ticket.id)
        )
        permission_comment = _(
            'Created by the ticket '
            'ticket title: {} '
            'ticket applicant: {} '
            'ticket processor: {} '
            'ticket ID: {}'
        ).format(
            self.ticket.title,
            self.ticket.applicant,
            ','.join([i['processor_display'] for i in self.ticket.process_map]),
            str(self.ticket.id)
        )

        permission_data = {
            'from_ticket': True,
            'id': self.ticket.id,
            'actions': apply_actions,
            'accounts': apply_accounts,
            'name': apply_permission_name,
            'date_start': apply_date_start,
            'date_expired': apply_date_expired,
            'comment': str(permission_comment),
            'created_by': permission_created_by,
        }
        with tmp_to_org(self.ticket.org_id):
            asset_permission = AssetPermission.objects.create(**permission_data)
            asset_permission.nodes.set(apply_nodes)
            asset_permission.assets.set(apply_assets)
            asset_permission.users.add(self.ticket.applicant)

        return asset_permission
