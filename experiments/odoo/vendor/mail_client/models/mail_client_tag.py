# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# IMAP keywords are atoms: no spaces and none of the characters that would
# terminate or nest a protocol token (RFC 3501 section 9).
_ILLEGAL_KEYWORD_CHARS = re.compile(r'[(){}%*"\\\]\[\s]+')

# Flags every server defines itself; they are mirrored onto dedicated boolean
# fields and must never be turned into user tags.
SYSTEM_FLAGS = {
    '\\seen', '\\answered', '\\flagged', '\\deleted', '\\draft', '\\recent',
}

# Thunderbird and friends store their labels as these; showing them as tags is
# right, but they should keep their familiar names.
COMMON_LABELS = {
    '$label1': 'Important',
    '$label2': 'Work',
    '$label3': 'Personal',
    '$label4': 'To Do',
    '$label5': 'Later',
    '$forwarded': 'Forwarded',
    'junk': 'Junk',
    'nonjunk': 'Not Junk',
}


class MailClientTag(models.Model):
    """A label on a message, backed by a real IMAP keyword.

    Dovecot stores arbitrary keywords in Maildir, so a tag applied in Odoo
    genuinely shows up in SOGo and on the phone, and labels applied elsewhere
    appear here. That is the whole point of doing this over IMAP rather than
    keeping a private list in Odoo.
    """
    _name = 'mail.client.tag'
    _description = 'Mail Client Tag'
    _order = 'name'

    name = fields.Char(required=True, translate=False)
    color = fields.Integer(default=0)
    account_id = fields.Many2one(
        'mail.client.account', required=True, ondelete='cascade', index=True,
        help="Keywords live inside one mailbox, so a tag belongs to one account.",
    )
    imap_keyword = fields.Char(
        required=True, readonly=True,
        help="The keyword as stored on the server.",
    )
    message_ids = fields.Many2many('mail.client.message', string='Messages')
    message_count = fields.Integer(compute='_compute_message_count')

    _keyword_account_uniq = models.Constraint(
        'UNIQUE(account_id, imap_keyword)',
        "That keyword already exists on this mailbox.",
    )

    def _compute_message_count(self):
        counts = dict(self.env['mail.client.message']._read_group(
            [('tag_ids', 'in', self.ids)], ['tag_ids'], ['__count'],
        ))
        for tag in self:
            tag.message_count = counts.get(tag, 0)

    @api.model
    def _sanitize_keyword(self, name):
        """Turn a human label into something IMAP will accept as an atom."""
        keyword = _ILLEGAL_KEYWORD_CHARS.sub('_', (name or '').strip())
        return keyword[:64] or 'Tag'

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get('imap_keyword'):
                values['imap_keyword'] = self._sanitize_keyword(values.get('name'))
        return super().create(vals_list)

    @api.constrains('imap_keyword')
    def _check_keyword(self):
        for tag in self:
            if _ILLEGAL_KEYWORD_CHARS.search(tag.imap_keyword or ''):
                raise ValidationError(_(
                    "'%s' cannot be used as an IMAP keyword: spaces and the "
                    "characters ( ) { } %% * \" \\ [ ] are not allowed.",
                    tag.imap_keyword,
                ))

    @api.model
    def _keywords_from_flags(self, flags):
        """Return the keyword flags, dropping the ones the server owns."""
        return [
            flag for flag in flags
            if flag and flag.lower() not in SYSTEM_FLAGS and not flag.startswith('\\')
        ]

    @api.model
    def _get_or_create(self, account, keyword):
        """Find the tag for a keyword seen on the server, creating it if new."""
        tag = self.search([
            ('account_id', '=', account.id), ('imap_keyword', '=ilike', keyword),
        ], limit=1)
        if tag:
            return tag
        return self.create({
            'account_id': account.id,
            'name': COMMON_LABELS.get(keyword.lower(), keyword),
            'imap_keyword': keyword,
        })
