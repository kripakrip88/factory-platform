# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MailClientAudit(models.Model):
    """Append-only record of master-user mailbox access.

    A credential that opens
    every mailbox is only acceptable if every use of it is attributable.
    """
    _name = 'mail.client.audit'
    _description = 'Mail Client Access Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'account_email'

    server_id = fields.Many2one('mail.client.server', ondelete='set null', index=True)
    account_id = fields.Many2one('mail.client.account', ondelete='set null', index=True)
    account_email = fields.Char(readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Acting User', ondelete='set null', index=True, readonly=True,
    )
    action = fields.Selection(
        [('imap_connect', 'IMAP Connection'), ('body_fetch', 'Message Body Fetch')],
        required=True, readonly=True,
    )
    auth_mode = fields.Selection(
        [('master', 'Master User'), ('per_account', 'Per-Account Password')],
        readonly=True,
    )
    detail = fields.Char(readonly=True)

    @api.model
    def log_access(self, server, account=None, action='imap_connect', detail=None):
        return self.sudo().create({
            'server_id': server.id,
            'account_id': account.id if account else False,
            'account_email': account.email if account else False,
            'user_id': self.env.user.id,
            'action': action,
            'auth_mode': server.auth_mode,
            'detail': detail,
        })

    def write(self, vals):
        raise UserError(_("Access log entries cannot be modified."))

    def unlink(self):
        # Retention is a policy decision; expose it as an explicit cron rather
        # than letting anyone quietly erase the trail from the UI.
        if not self.env.context.get('mail_client_audit_gc'):
            raise UserError(_("Access log entries cannot be deleted."))
        return super().unlink()

    @api.model
    def _cron_gc_audit(self, months=12):
        cutoff = fields.Datetime.now() - relativedelta(months=months)
        stale = self.search([('create_date', '<', cutoff)])
        return stale.with_context(mail_client_audit_gc=True).unlink()
