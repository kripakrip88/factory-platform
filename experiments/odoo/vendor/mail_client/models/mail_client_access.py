# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MailClientAccess(models.Model):
    """Who may open a shared mailbox, and in what capacity.

    The Dovecot master user makes shared mailboxes nearly free: there is no
    second credential to manage, so info@ and sales@ are ordinary accounts
    with no owner.
    """
    _name = 'mail.client.access'
    _description = 'Mail Client Access'
    _order = 'account_id, user_id'

    account_id = fields.Many2one(
        'mail.client.account', required=True, ondelete='cascade', index=True,
    )
    user_id = fields.Many2one(
        'res.users', required=True, ondelete='cascade', index=True,
        domain=[('share', '=', False)],
    )
    role = fields.Selection(
        [('viewer', 'Viewer'), ('agent', 'Agent'), ('manager', 'Manager')],
        default='agent', required=True,
        help="Viewer: read only.\n"
             "Agent: read, reply, flag, tag, move and delete.\n"
             "Manager: everything an agent can do, plus managing this access list.",
    )

    _account_user_uniq = models.Constraint(
        'UNIQUE(account_id, user_id)',
        "This user already has access to that mailbox.",
    )

    # ------------------------------------------------------------------
    # Keep mail.client.account.allowed_user_ids in step. Record rules read
    # that field, so any drift here is a data leak or a lockout.
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.account_id._recompute_allowed_users()
        return records

    def write(self, vals):
        previous_accounts = self.account_id
        result = super().write(vals)
        (previous_accounts | self.account_id)._recompute_allowed_users()
        return result

    def unlink(self):
        accounts = self.account_id
        result = super().unlink()
        accounts._recompute_allowed_users()
        return result

    @api.constrains('account_id', 'user_id')
    def _check_not_owner(self):
        for access in self:
            if access.account_id.user_id == access.user_id:
                raise ValidationError(_(
                    "%s already owns this mailbox and does not need an access entry.",
                    access.user_id.display_name,
                ))
