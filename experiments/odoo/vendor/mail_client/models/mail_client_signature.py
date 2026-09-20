# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
from markupsafe import Markup

from odoo import api, fields, models


class MailClientSignature(models.Model):
    """A signature block appended when composing.

    Kept per mailbox rather than per user: someone answering from sales@ signs
    differently than from their own address, and that is the common case for
    the shared mailboxes this module supports.
    """
    _name = 'mail.client.signature'
    _description = 'Mail Client Signature'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    account_id = fields.Many2one(
        'mail.client.account', required=True, ondelete='cascade', index=True,
    )
    body_html = fields.Html(sanitize=False, sanitize_attributes=False)
    is_default = fields.Boolean(
        string='Use by Default',
        help="Inserted automatically when writing from this mailbox.",
    )
    use_on_reply = fields.Boolean(
        default=True,
        help="Untick to keep replies clean and only sign new messages.",
    )

    @api.constrains('is_default', 'account_id')
    def _check_single_default(self):
        for signature in self.filtered('is_default'):
            others = self.search([
                ('account_id', '=', signature.account_id.id),
                ('is_default', '=', True),
                ('id', '!=', signature.id),
            ])
            # Silently demoting the previous default is friendlier than
            # refusing the save and making the user hunt for it.
            others.is_default = False

    @api.model
    def _default_for(self, account, mode='new'):
        signature = self.search([
            ('account_id', '=', account.id), ('is_default', '=', True),
        ], limit=1)
        if not signature:
            return None
        if mode != 'new' and not signature.use_on_reply:
            return None
        return signature

    def _as_block(self):
        """Wrap the signature so a reply can be inserted above it."""
        self.ensure_one()
        if not self.body_html:
            return Markup('')
        return Markup(
            '<div class="o_mail_client_signature" data-signature-id="%s">'
            '<p><br/></p>%s</div>'
        ) % (self.id, Markup(self.body_html))
