# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Download a message exactly as the server holds it.

Useful when a mail has to be forwarded as an attachment, handed to someone for
header analysis, or kept outside Odoo. The original is fetched on demand
rather than stored, in keeping with the rest of the module.
"""
import logging
import re

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..tools.imap_client import ImapError

_logger = logging.getLogger(__name__)

_RE_UNSAFE = re.compile(r'[^\w.\- ]+')


class MailClientDownload(http.Controller):

    @http.route('/mail_client/message/<int:message_id>/eml', type='http',
                auth='user', methods=['GET'])
    def download_eml(self, message_id, **kwargs):
        message = request.env['mail.client.message'].browse(message_id).exists()
        if not message:
            return request.not_found()
        try:
            # Access is checked as the real user; only the IMAP fetch is sudo.
            message.check_access('read')
        except AccessError:
            return request.not_found()

        message = message.sudo()
        connection = None
        try:
            connection = message.account_id._open_connection()
            connection.select(message.folder_id.imap_path, readonly=True)
            raw = connection.fetch_raw(message.imap_uid)
        except (ImapError, UserError) as exc:
            _logger.warning("Mail Client: .eml download failed for UID %s: %s",
                            message.imap_uid, exc)
            return request.make_response(
                "This message could not be downloaded from the mail server.",
                headers=[('Content-Type', 'text/plain')], status=502,
            )
        finally:
            if connection:
                connection.close()

        filename = _RE_UNSAFE.sub('_', message.subject or 'message')[:80].strip() or 'message'
        return request.make_response(raw, headers=[
            ('Content-Type', 'message/rfc822'),
            ('Content-Disposition', 'attachment; filename="%s.eml"' % filename),
            ('Content-Length', len(raw)),
        ])
