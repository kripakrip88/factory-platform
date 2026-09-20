# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..tools import crypto
from ..tools.imap_client import ImapConnection, ImapError

_logger = logging.getLogger(__name__)

PASSWORD_PLACEHOLDER = '••••••••'


class MailClientServer(models.Model):
    """A mail server (typically one mailcow instance).

    Infrastructure credentials live here and nowhere else. Individual accounts
    point at this record instead of each carrying a password, which is what
    makes the Dovecot master user approach work.
    """
    _name = 'mail.client.server'
    _description = 'Mail Client Server'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    imap_host = fields.Char(string='IMAP Host', required=True)
    imap_port = fields.Integer(string='IMAP Port', default=993, required=True)
    imap_encryption = fields.Selection(
        [('ssl', 'SSL/TLS'), ('starttls', 'STARTTLS'), ('none', 'None')],
        string='Encryption', default='ssl', required=True,
    )
    smtp_server_id = fields.Many2one(
        'ir.mail_server', string='Default Outgoing Server',
        help="Fallback only, used by mailboxes on this server that have no "
             "outgoing server of their own.\n\n"
             "Sending is per mailbox: a mail server that enforces sender-login "
             "matching - mailcow and Gmail both do - refuses to let one account "
             "send as another. So this default can only ever be correct for one "
             "mailbox, and is best left empty when several share this server.",
    )

    auth_mode = fields.Selection(
        [('master', 'Dovecot Master User'), ('per_account', 'Per-Account Password')],
        default='master', required=True,
        help="Master User: one admin credential opens every mailbox, so no user "
             "password is ever stored in Odoo.\n"
             "Per-Account: each account carries its own password. More tedious, "
             "but nothing in Odoo can reach the whole mail system.",
    )
    master_user = fields.Char(
        string='Master User',
        help="The DOVECOT_MASTER_USER value from mailcow.conf.",
    )
    master_realm = fields.Char(
        string='Master Realm', default='mailcow.local',
        help="mailcow expands the master user to <user>@<realm>.",
    )
    master_password = fields.Char(
        string='Master Password', groups='base.group_system',
        compute='_compute_master_password', inverse='_inverse_master_password',
        help="Stored encrypted with a key held in odoo.conf, never in the database.",
    )
    master_password_encrypted = fields.Char(
        groups='base.group_system', copy=False, readonly=True,
    )

    capabilities = fields.Char(readonly=True, copy=False)
    supports_qresync = fields.Boolean(readonly=True, copy=False)
    supports_move = fields.Boolean(readonly=True, copy=False)

    state = fields.Selection(
        [('draft', 'Not Tested'), ('connected', 'Connected'), ('error', 'Error')],
        default='draft', readonly=True, copy=False,
    )
    error_message = fields.Text(readonly=True, copy=False)
    account_ids = fields.One2many('mail.client.account', 'server_id', string='Accounts')
    account_count = fields.Integer(compute='_compute_account_count')

    _imap_port_range = models.Constraint(
        'CHECK(imap_port > 0 AND imap_port < 65536)',
        "The IMAP port must be between 1 and 65535.",
    )

    @api.depends('account_ids')
    def _compute_account_count(self):
        counts = dict(self.env['mail.client.account']._read_group(
            [('server_id', 'in', self.ids)], ['server_id'], ['__count'],
        ))
        for server in self:
            server.account_count = counts.get(server, 0)

    @api.depends('master_password_encrypted')
    def _compute_master_password(self):
        # Never send the real secret to the client, not even to an administrator.
        for server in self:
            server.master_password = PASSWORD_PLACEHOLDER if server.master_password_encrypted else False

    def _inverse_master_password(self):
        for server in self:
            value = server.master_password
            if value == PASSWORD_PLACEHOLDER:
                continue  # form was saved without touching the field
            server.master_password_encrypted = crypto.encrypt(value) if value else False

    @api.onchange('imap_port')
    def _onchange_imap_port(self):
        """Keep port and TLS mode consistent.

        Mismatching them produces a bare 30-second timeout with no explanation,
        so it is worth steering away from before the connection is ever tried.
        """
        if self.imap_port == 993 and self.imap_encryption != 'ssl':
            self.imap_encryption = 'ssl'
        elif self.imap_port == 143 and self.imap_encryption == 'ssl':
            self.imap_encryption = 'starttls'

    @api.constrains('auth_mode', 'master_user')
    def _check_master_configuration(self):
        for server in self:
            if server.auth_mode == 'master' and not server.master_user:
                raise ValidationError(_(
                    "Master authentication requires the master user name "
                    "(DOVECOT_MASTER_USER in mailcow.conf)."
                ))

    # ------------------------------------------------------------------
    # connection
    # ------------------------------------------------------------------
    def _build_login(self, account):
        """Return the ``(login, password)`` pair used to open ``account``."""
        self.ensure_one()
        if self.auth_mode == 'master':
            password = crypto.decrypt(self.sudo().master_password_encrypted)
            if not password:
                raise UserError(_("No master password is configured on server '%s'.", self.name))
            realm = self.master_realm or 'mailcow.local'
            # mailcow syntax: <mailbox>*<master_user>@<realm>
            return '%s*%s@%s' % (account.email, self.master_user, realm), password

        login = account.login or account.email
        password = crypto.decrypt(account.sudo().password_encrypted)
        if not password:
            raise UserError(_("No password is configured on account '%s'.", account.display_name))
        return login, password

    def _probe(self):
        """Open the transport only, without logging in.

        A Dovecot master user is not a mailbox of its own: it can only be used
        as ``target*master@realm``. So when no account exists yet there is
        nothing to authenticate against, and the most useful thing a connection
        test can do is verify the host, port, TLS mode and capabilities.
        """
        self.ensure_one()
        connection = ImapConnection(
            self.imap_host, self.imap_port, self.imap_encryption, None, None,
        )
        connection.connect(authenticate=False)
        return connection

    def _connect(self, account=None):
        """Open an authenticated IMAP session, logging master-user access."""
        self.ensure_one()
        if not account:
            raise UserError(_(
                "A mailbox is required to open an IMAP session: the master user "
                "can only be used to log into a specific mailbox."
            ))
        login, password = self._build_login(account)

        connection = ImapConnection(
            self.imap_host, self.imap_port, self.imap_encryption, login, password,
        )
        connection.connect()

        if self.auth_mode == 'master' and account:
            # Master access without an audit
            # trail is indistinguishable from abuse.
            self.env['mail.client.audit'].sudo().log_access(
                server=self, account=account, action='imap_connect',
            )
        return connection

    def action_test_connection(self):
        self.ensure_one()
        account = self.account_ids[:1]
        connection = None
        try:
            connection = self._connect(account=account) if account else self._probe()
            folders = connection.list_folders() if account else []
            values = {'state': 'connected', 'error_message': False}
            if connection.authenticated:
                # Only a post-login CAPABILITY is meaningful. Recording the
                # pre-auth one would claim QRESYNC is missing on a server that
                # supports it perfectly well.
                values.update({
                    'capabilities': ' '.join(sorted(connection.capabilities)),
                    'supports_qresync': connection.supports_qresync,
                    'supports_move': connection.supports_move,
                })
            self.write(values)
        except (ImapError, UserError) as exc:
            self.write({'state': 'error', 'error_message': str(exc)})
            raise UserError(_("Connection failed:\n\n%s", exc)) from exc
        finally:
            if connection:
                connection.close()

        message = _("Reached %(host)s:%(port)s over %(encryption)s.",
                    host=self.imap_host, port=self.imap_port,
                    encryption=(self.imap_encryption or '').upper())
        if account:
            message += _("\n\nSigned in to '%(email)s', which exposes %(count)s folders.",
                         email=account.email, count=len(folders))
            if not self.supports_qresync:
                message += _("\n\nWarning: this server does not advertise QRESYNC. "
                             "Sync will use the slower full-UID comparison.")
        else:
            message += _("\n\nCredentials and server capabilities were NOT checked: the "
                         "master user can only sign into a specific mailbox, and IMAP "
                         "servers only advertise their full capability list after login. "
                         "Add a mail account, then test again.")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Success"), 'message': message, 'type': 'success', 'sticky': False},
        }

    def action_view_accounts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Mail Accounts"),
            'res_model': 'mail.client.account',
            'view_mode': 'list,form',
            'domain': [('server_id', '=', self.id)],
            'context': {'default_server_id': self.id},
        }
