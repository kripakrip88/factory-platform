# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import logging
import re
from datetime import timedelta
from email.utils import make_msgid

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext
from odoo.tools.mail import email_split_and_format, html_sanitize

from ..tools.imap_client import ImapError

_logger = logging.getLogger(__name__)

_RE_MESSAGE_ID = re.compile(r'<[^>]+>')


class MailClientCompose(models.Model):
    """A message being written.

    Kept as a regular model rather than a wizard so that attachments uploaded
    before sending have somewhere to live, and so an interrupted draft is not
    silently lost when the browser is closed.
    """
    _name = 'mail.client.compose'
    _description = 'Mail Client Composer'
    _order = 'write_date desc, id desc'

    account_id = fields.Many2one(
        'mail.client.account', required=True, ondelete='cascade', index=True,
    )
    user_id = fields.Many2one(
        'res.users', required=True, default=lambda self: self.env.user,
        ondelete='cascade', index=True,
    )

    email_to = fields.Char(string='To')
    email_cc = fields.Char(string='Cc')
    email_bcc = fields.Char(string='Bcc')
    subject = fields.Char()
    body_html = fields.Html(sanitize=False, sanitize_attributes=False)

    parent_id = fields.Many2one(
        'mail.client.message', string='In Reply To', ondelete='set null',
        help="Set for replies and forwards; drives the threading headers.",
    )
    compose_mode = fields.Selection(
        [('new', 'New'), ('reply', 'Reply'), ('reply_all', 'Reply All'), ('forward', 'Forward')],
        default='new', required=True,
    )

    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    imap_draft_uid = fields.Integer(
        readonly=True, copy=False,
        help="UID of the copy filed in the server's Drafts folder, so a "
             "re-save can replace it instead of adding another one.",
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('sent', 'Sent'), ('failed', 'Failed')],
        default='draft', required=True, index=True,
    )
    error_message = fields.Text()
    sent_date = fields.Datetime(readonly=True)

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------
    def _recipients(self):
        self.ensure_one()
        recipients = []
        for field in ('email_to', 'email_cc', 'email_bcc'):
            recipients += email_split_and_format(self[field] or '')
        return recipients

    def _threading_headers(self):
        """Build In-Reply-To and References so replies stay in their thread.

        Adding "Re:" to the subject is not threading: every serious mail client
        follows these headers, and so does the piler archive.
        """
        self.ensure_one()
        parent = self.parent_id
        if not parent or not parent.message_id:
            return '', {}
        references = _RE_MESSAGE_ID.findall(parent.references or '')
        references.append(parent.message_id)
        # Trim the chain: some clients choke on very long References headers.
        return ' '.join(references[-20:]), {'In-Reply-To': parent.message_id}

    def action_send(self):
        self.ensure_one()
        if not self._recipients():
            raise UserError(_("Add at least one recipient before sending."))

        account = self.account_id
        mail_server = account._resolve_mail_server()
        if not mail_server:
            raise UserError(_(
                "No outgoing mail server is available for %(email)s.\n\n"
                "The Dovecot master user does not cover SMTP submission, so "
                "sending needs its own credentials - a mailcow app password "
                "restricted to SMTP is the safest choice. Set one on this "
                "mailbox, on the user, or on '%(server)s'.",
                email=account.email, server=account.server_id.name,
            ))
        account._check_sender_allowed(mail_server)

        IrMailServer = self.env['ir.mail_server'].sudo()
        message_id = make_msgid(domain=(account.email or '@').split('@')[-1])
        message = self._build_message(message_id=message_id)

        try:
            IrMailServer.send_email(
                message,
                mail_server_id=mail_server.id,
                smtp_session=None,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            _logger.warning("Mail Client: sending failed for %s: %s", account.email, exc)
            self.write({'state': 'failed', 'error_message': str(exc)})
            raise UserError(_("The message could not be sent:\n\n%s", exc)) from exc

        self.write({
            'state': 'sent',
            'sent_date': fields.Datetime.now(),
            'error_message': False,
        })
        self._append_to_sent(message)
        # The draft is no longer a draft anywhere.
        self._remove_imap_draft()
        self._mark_parent_answered()
        return True

    def _build_message(self, message_id=None):
        """Assemble the MIME message for this draft."""
        self.ensure_one()
        references, headers = self._threading_headers()
        return self.env['ir.mail_server'].sudo()._build_email__(
            email_from=self.account_id.email,
            email_to=email_split_and_format(self.email_to or ''),
            subject=self.subject or '',
            body=html_sanitize(self.body_html or ''),
            email_cc=email_split_and_format(self.email_cc or ''),
            email_bcc=email_split_and_format(self.email_bcc or ''),
            attachments=[
                (attachment.name, attachment.raw, attachment.mimetype)
                for attachment in self.attachment_ids
            ],
            message_id=message_id or make_msgid(
                domain=(self.account_id.email or '@').split('@')[-1]
            ),
            references=references,
            subtype='html',
            headers=headers,
        )

    def _sync_to_imap_drafts(self):
        """Mirror this draft into the server's Drafts folder.

        Without it the draft exists only inside Odoo, so it is invisible in
        SOGo and on the phone. The previous copy is removed first: APPEND
        always creates a new message, so saving five times would otherwise
        leave five drafts behind.
        """
        self.ensure_one()
        drafts = self.account_id.folder_ids.filtered(lambda f: f.role == 'drafts')[:1]
        if not drafts:
            return False

        connection = None
        try:
            connection = self.account_id._open_connection()
            if self.imap_draft_uid:
                try:
                    connection.select(drafts.imap_path, readonly=False)
                    connection.store_flags(self.imap_draft_uid, ['\\Deleted'], add=True)
                    connection.expunge(self.imap_draft_uid)
                except ImapError as exc:
                    # Already gone, or the folder changed underneath us. Losing
                    # the old copy is not worth failing the save over.
                    _logger.info("Mail Client: could not remove previous draft copy: %s", exc)
            uid = connection.append(
                drafts.imap_path, self._build_message().as_bytes(), flags=('\\Draft', '\\Seen'),
            )
            self.write({'imap_draft_uid': uid or 0})
        except (ImapError, UserError) as exc:
            _logger.warning("Mail Client: draft could not be filed on the server: %s", exc)
            return False
        finally:
            if connection:
                connection.close()
        return True

    def _remove_imap_draft(self):
        """Drop the server-side copy once the draft is sent or discarded."""
        self.ensure_one()
        if not self.imap_draft_uid:
            return False
        drafts = self.account_id.folder_ids.filtered(lambda f: f.role == 'drafts')[:1]
        if not drafts:
            return False

        connection = None
        try:
            connection = self.account_id._open_connection()
            connection.select(drafts.imap_path, readonly=False)
            connection.store_flags(self.imap_draft_uid, ['\\Deleted'], add=True)
            connection.expunge(self.imap_draft_uid)
        except (ImapError, UserError) as exc:
            _logger.info("Mail Client: leftover draft copy could not be removed: %s", exc)
            return False
        finally:
            if connection:
                connection.close()
        self.write({'imap_draft_uid': 0})
        return True

    def _append_to_sent(self, message):
        """File the sent message in the server's Sent folder.

        Without this the mail exists only in Odoo, and the copy in SOGo,
        Thunderbird or the user's phone is simply missing.
        """
        self.ensure_one()
        sent_folder = self.account_id.folder_ids.filtered(lambda f: f.role == 'sent')[:1]
        if not sent_folder:
            _logger.info("Mail Client: no Sent folder on %s; skipping APPEND.",
                         self.account_id.email)
            return False

        connection = None
        try:
            connection = self.account_id._open_connection()
            connection.append(sent_folder.imap_path, message.as_bytes(), flags=('\\Seen',))
        except (ImapError, UserError) as exc:
            # The mail is already delivered; failing to file a copy must not
            # look like a send failure.
            _logger.warning("Mail Client: APPEND to Sent failed for %s: %s",
                            self.account_id.email, exc)
            return False
        finally:
            if connection:
                connection.close()
        return True

    def _mark_parent_answered(self):
        self.ensure_one()
        if self.compose_mode in ('reply', 'reply_all') and self.parent_id:
            self.parent_id._set_flag('\\Answered', True)

    # ------------------------------------------------------------------
    # client action RPC
    # ------------------------------------------------------------------
    @api.model
    def start(self, account_id, mode='new', message_id=None):
        """Create a draft, pre-filled for a reply or a forward."""
        account = self.env['mail.client.account'].browse(account_id).exists()
        if not account:
            raise UserError(_("This mailbox no longer exists."))
        account.check_access('read')

        values = {'account_id': account.id, 'compose_mode': mode}
        if message_id:
            parent = self.env['mail.client.message'].browse(message_id).exists()
            if parent:
                parent.check_access('read')
                values.update(self._prepare_from_parent(parent, mode, account))

        signature = self.env['mail.client.signature']._default_for(account, mode)
        if signature:
            # Above the quoted original, where a reader expects it.
            values['body_html'] = Markup('%s%s') % (
                signature._as_block(), Markup(values.get('body_html') or ''),
            )

        draft = self.create(values)
        return draft._to_payload()

    @api.model
    def _prepare_from_parent(self, parent, mode, account):
        subject = parent.subject or ''
        values = {'parent_id': parent.id}

        if mode == 'forward':
            values['subject'] = subject if subject.lower().startswith('fwd:') else 'Fwd: %s' % subject
            values['email_to'] = ''
        else:
            values['subject'] = subject if subject.lower().startswith('re:') else 'Re: %s' % subject
            values['email_to'] = parent.email_from or ''
            if mode == 'reply_all':
                # Everyone on the original except ourselves, or we mail our own inbox.
                others = email_split_and_format(
                    '%s, %s' % (parent.email_to or '', parent.email_cc or '')
                )
                own = (account.email or '').lower()
                values['email_cc'] = ', '.join(
                    address for address in others if own not in address.lower()
                )

        if parent.body_state == 'header_only':
            parent.sudo()._fetch_body()
            parent.invalidate_recordset()
        values['body_html'] = parent._quoted_body()
        return values

    def _to_payload(self):
        self.ensure_one()
        return {
            'id': self.id,
            'account_id': self.account_id.id,
            'compose_mode': self.compose_mode,
            'email_to': self.email_to or '',
            'email_cc': self.email_cc or '',
            'email_bcc': self.email_bcc or '',
            'subject': self.subject or '',
            # The composer writes this straight into a contenteditable, so it
            # must be safe before it leaves the server. Sanitising here also
            # keeps the editor honest: this is exactly what _build_email sends.
            'body_html': html_sanitize(self.body_html or ''),
            'state': self.state,
            'attachments': [{
                'id': attachment.id,
                'name': attachment.name,
                'size': attachment.file_size,
            } for attachment in self.attachment_ids],
        }

    @api.model
    def save_draft(self, compose_id, values):
        draft = self.browse(compose_id).exists()
        if not draft:
            raise UserError(_("This draft no longer exists."))
        draft.check_access('write')
        allowed = {'email_to', 'email_cc', 'email_bcc', 'subject', 'body_html'}
        draft.write({key: value for key, value in (values or {}).items() if key in allowed})
        # Filing on the server is best-effort: a save must still succeed when
        # the mail server is unreachable.
        draft.sudo()._sync_to_imap_drafts()
        return draft._to_payload()

    @api.model
    def send(self, compose_id, values=None):
        draft = self.browse(compose_id).exists()
        if not draft:
            raise UserError(_("This draft no longer exists."))
        draft.check_access('write')
        if values:
            self.save_draft(compose_id, values)
            draft.invalidate_recordset()
        draft.sudo().action_send()
        return {'id': draft.id, 'state': draft.state}

    @api.model
    def attach(self, compose_id, name, datas, mimetype=None):
        draft = self.browse(compose_id).exists()
        if not draft:
            raise UserError(_("This draft no longer exists."))
        draft.check_access('write')
        attachment = self.env['ir.attachment'].create({
            'name': name,
            'datas': datas,
            'mimetype': mimetype or 'application/octet-stream',
            'res_model': self._name,
            'res_id': draft.id,
        })
        draft.attachment_ids = [fields.Command.link(attachment.id)]
        return draft._to_payload()

    @api.model
    def detach(self, compose_id, attachment_id):
        draft = self.browse(compose_id).exists()
        if not draft:
            raise UserError(_("This draft no longer exists."))
        draft.check_access('write')
        draft.attachment_ids = [fields.Command.unlink(attachment_id)]
        return draft._to_payload()

    @api.model
    def search_recipients(self, term, limit=8):
        """Suggest contacts while the user types a recipient.

        Only partners that actually have an email are useful here - suggesting
        a contact you cannot send to is worse than suggesting nothing.
        """
        term = (term or '').strip()
        if len(term) < 2:
            return []
        partners = self.env['res.partner'].search(
            ['&', ('email', '!=', False),
             '|', '|', ('name', 'ilike', term), ('email', 'ilike', term),
             ('parent_id.name', 'ilike', term)],
            limit=limit,
        )
        return [{
            'id': partner.id,
            'name': partner.name or '',
            'email': partner.email,
            'company': partner.parent_id.name or '',
            'value': '"%s" <%s>' % (partner.name, partner.email) if partner.name else partner.email,
        } for partner in partners]

    @api.model
    def _cron_gc_empty_drafts(self, hours=24):
        """Remove drafts nothing was ever typed into.

        The composer discards an untouched draft on close, but a browser that
        is closed mid-compose leaves one behind. Without this they accumulate
        as a list of "(no subject)" entries nobody can act on.
        """
        cutoff = fields.Datetime.now() - timedelta(hours=hours)
        stale = self.search([
            ('state', '=', 'draft'),
            ('write_date', '<', cutoff),
            ('email_to', 'in', [False, '']),
            ('email_cc', 'in', [False, '']),
            ('email_bcc', 'in', [False, '']),
            ('subject', 'in', [False, '']),
            ('attachment_ids', '=', False),
        ])
        empty = stale.filtered(
            lambda draft: not html2plaintext(draft.body_html or '').strip()
        )
        return empty.unlink()

    @api.model
    def list_drafts(self, account_id):
        """Unsent drafts for this mailbox, newest first."""
        drafts = self.search([
            ('account_id', '=', account_id),
            ('state', '=', 'draft'),
            ('user_id', '=', self.env.uid),
        ])
        return [{
            'id': draft.id,
            'subject': draft.subject or _("(no subject)"),
            'email_to': draft.email_to or '',
            'write_date': fields.Datetime.to_string(draft.write_date),
            'attachment_count': len(draft.attachment_ids),
        } for draft in drafts]

    @api.model
    def open_draft(self, compose_id):
        draft = self.browse(compose_id).exists()
        if not draft:
            raise UserError(_("This draft no longer exists."))
        draft.check_access('write')
        return draft._to_payload()

    @api.model
    def discard(self, compose_id):
        draft = self.browse(compose_id).exists()
        if draft:
            draft.check_access('unlink')
            draft.sudo()._remove_imap_draft()
            draft.unlink()
        return True
