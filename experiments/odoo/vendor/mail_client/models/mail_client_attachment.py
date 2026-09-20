# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools.imap_client import ImapError

_logger = logging.getLogger(__name__)


class MailClientAttachment(models.Model):
    """One MIME part of a message, described but not necessarily downloaded.

    BODYSTRUCTURE gives us the name, type and size of every attachment for
    free. Only when a user actually clicks one do we pull that single part
    down and turn it into an ir.attachment - so a mailbox full of 10 MB PDFs
    costs a few hundred bytes per message until someone wants them.
    """
    _name = 'mail.client.attachment'
    _description = 'Mail Client Attachment'
    _order = 'message_id, sequence, id'

    message_id = fields.Many2one(
        'mail.client.message', required=True, ondelete='cascade', index=True,
    )
    account_id = fields.Many2one(related='message_id.account_id', store=True, index=True)
    sequence = fields.Integer(default=10)

    name = fields.Char(required=True)
    part_number = fields.Char(required=True, help="IMAP part address, e.g. 2 or 1.3")
    content_type = fields.Char()
    encoding = fields.Char()
    file_size = fields.Integer(help="Encoded size as reported by the server.")

    attachment_id = fields.Many2one(
        'ir.attachment', ondelete='set null', copy=False,
        help="Filled in once the part has actually been downloaded.",
    )
    state = fields.Selection(
        [('remote', 'On server'), ('fetched', 'Downloaded'), ('failed', 'Failed')],
        default='remote', required=True,
    )
    error_message = fields.Char()

    _part_message_uniq = models.Constraint(
        'UNIQUE(message_id, part_number)',
        "This part is already recorded for that message.",
    )

    def _fetch(self):
        """Download this part and store it as an ir.attachment."""
        self.ensure_one()
        if self.state == 'fetched' and self.attachment_id:
            return self.attachment_id

        message = self.message_id
        connection = None
        try:
            connection = message.account_id._open_connection()
            connection.select(message.folder_id.imap_path, readonly=True)
            payload = connection.fetch_part(
                message.imap_uid, self.part_number, self.encoding,
            )
        except (ImapError, UserError) as exc:
            self.write({'state': 'failed', 'error_message': str(exc)[:255]})
            raise UserError(_("This attachment could not be downloaded:\n\n%s", exc)) from exc
        finally:
            if connection:
                connection.close()

        attachment = self.env['ir.attachment'].sudo().create({
            'name': self.name,
            'datas': base64.b64encode(payload),
            'mimetype': self.content_type or 'application/octet-stream',
            'res_model': 'mail.client.message',
            'res_id': message.id,
        })
        self.write({
            'attachment_id': attachment.id,
            'state': 'fetched',
            'error_message': False,
        })
        self.env['mail.client.audit'].sudo().log_access(
            server=message.account_id.server_id, account=message.account_id,
            action='body_fetch', detail=_("Attachment %s", self.name),
        )
        return attachment

    @api.model
    def download(self, attachment_id):
        """Fetch on demand and hand back a URL the browser can open."""
        record = self.browse(attachment_id).exists()
        if not record:
            raise UserError(_("This attachment no longer exists."))
        record.message_id.check_access('read')

        attachment = record.sudo()._fetch()
        return {
            'id': record.id,
            'name': record.name,
            'url': '/web/content/%s?download=true' % attachment.id,
            'attachment_id': attachment.id,
        }
