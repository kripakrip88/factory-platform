# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import logging
from datetime import timedelta

from odoo import api, fields, models

from ..tools.imap_client import ImapError

_logger = logging.getLogger(__name__)

MAX_RETRIES = 5


class MailClientSyncOp(models.Model):
    """Outbox of mutations waiting to reach the IMAP server.

    Marking a message read must not block on the network, and it must survive
    a dropped connection. So user actions are recorded here and pushed later,
    always *before* the next fetch - otherwise a stale server state would
    overwrite what the user just did.
    """
    _name = 'mail.client.sync.op'
    _description = 'Mail Client Pending Operation'
    _order = 'create_date, id'

    account_id = fields.Many2one(
        'mail.client.account', required=True, ondelete='cascade', index=True,
    )
    folder_id = fields.Many2one('mail.client.folder', ondelete='cascade', index=True)
    message_id = fields.Many2one('mail.client.message', ondelete='set null', index=True)
    imap_uid = fields.Integer(
        required=True,
        help="Kept alongside the message so the operation still makes sense "
             "once the local record is gone.",
    )
    imap_path = fields.Char(required=True)

    op_type = fields.Selection(
        [('set_flag', 'Set Flag'),
         ('unset_flag', 'Unset Flag'),
         ('move', 'Move'),
         ('delete', 'Delete')],
        required=True,
    )
    payload = fields.Json(default=dict)

    state = fields.Selection(
        [('pending', 'Pending'), ('done', 'Done'), ('failed', 'Failed')],
        default='pending', required=True, index=True,
    )
    retry_count = fields.Integer(default=0)
    last_error = fields.Char()

    @api.model
    def queue(self, message, op_type, payload=None):
        """Record an operation for a message."""
        return self.sudo().create({
            'account_id': message.account_id.id,
            'folder_id': message.folder_id.id,
            'message_id': message.id,
            'imap_uid': message.imap_uid,
            'imap_path': message.folder_id.imap_path,
            'op_type': op_type,
            'payload': payload or {},
        })

    def _push(self, connection):
        """Execute pending operations over an open, writable connection."""
        by_folder = {}
        for operation in self.filtered(lambda o: o.state == 'pending'):
            by_folder.setdefault(operation.imap_path, self.browse())
            by_folder[operation.imap_path] |= operation

        for imap_path, operations in by_folder.items():
            try:
                connection.select(imap_path, readonly=False)
            except ImapError as exc:
                operations._fail(str(exc))
                continue
            for operation in operations:
                operation._execute(connection)

    def _execute(self, connection):
        self.ensure_one()
        try:
            if self.op_type in ('set_flag', 'unset_flag'):
                flags = self.payload.get('flags') or []
                connection.store_flags(
                    self.imap_uid, flags, add=self.op_type == 'set_flag',
                )
            elif self.op_type == 'move':
                connection.move(self.imap_uid, self.payload.get('target_path'))
            elif self.op_type == 'delete':
                connection.store_flags(self.imap_uid, ['\\Deleted'], add=True)
                connection.expunge(self.imap_uid)
        except ImapError as exc:
            message = str(exc)
            # A message that no longer exists server-side is not a failure:
            # the intent (it should be gone / changed) is already satisfied.
            if 'NO' in message.upper() and self.op_type in ('move', 'delete'):
                _logger.info("Mail Client: op %s on UID %s already moot: %s",
                             self.op_type, self.imap_uid, exc)
                self.write({'state': 'done', 'last_error': message[:255]})
            else:
                self._fail(message)
            return False

        self.write({'state': 'done', 'last_error': False})
        return True

    def _fail(self, error):
        for operation in self:
            retries = operation.retry_count + 1
            operation.write({
                'retry_count': retries,
                'last_error': (error or '')[:255],
                'state': 'failed' if retries >= MAX_RETRIES else 'pending',
            })
            if retries >= MAX_RETRIES:
                _logger.warning(
                    "Mail Client: giving up on %s for UID %s after %s attempts: %s",
                    operation.op_type, operation.imap_uid, retries, error,
                )

    @api.model
    def _cron_gc_done(self, days=7):
        cutoff = fields.Datetime.now() - timedelta(days=days)
        return self.search([('state', '=', 'done'), ('create_date', '<', cutoff)]).unlink()

    def action_retry(self):
        self.write({'state': 'pending', 'retry_count': 0, 'last_error': False})
        return True
