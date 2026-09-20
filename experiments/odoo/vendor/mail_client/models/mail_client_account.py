# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.mail import email_normalize

from ..tools import crypto
from ..tools.imap_client import ImapConnection, ImapError

_logger = logging.getLogger(__name__)

PASSWORD_PLACEHOLDER = '••••••••'

# RFC 6154 SPECIAL-USE attributes. Dovecot advertises these, so folder roles are
# detected rather than guessed from names.
SPECIAL_USE_ROLES = {
    '\\INBOX': 'inbox',
    '\\SENT': 'sent',
    '\\DRAFTS': 'drafts',
    '\\TRASH': 'trash',
    '\\JUNK': 'spam',
    '\\ARCHIVE': 'archive',
    '\\ALL': 'archive',
}

# Fallback for servers that do not implement SPECIAL-USE.
NAME_ROLES = {
    'inbox': 'inbox',
    'sent': 'sent', 'sent items': 'sent', 'terkirim': 'sent',
    'drafts': 'drafts', 'draft': 'drafts', 'konsep': 'drafts',
    'trash': 'trash', 'deleted items': 'trash', 'sampah': 'trash',
    'junk': 'spam', 'spam': 'spam',
    'archive': 'archive', 'arsip': 'archive',
}


class MailClientAccount(models.Model):
    _name = 'mail.client.account'
    _description = 'Mail Client Account'
    _order = 'sequence, name'
    _inherit = ['google.gmail.mixin', 'microsoft.outlook.mixin']

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    email = fields.Char(string='Email Address', required=True)
    color = fields.Integer()

    server_id = fields.Many2one(
        'mail.client.server', string='Mail Server', ondelete='restrict',
        help="Leave empty for external Gmail / Microsoft 365 accounts.",
    )
    account_type = fields.Selection(
        [('mailcow', 'Self-hosted (mailcow / Dovecot)'),
         ('imap', 'Generic IMAP'),
         ('gmail', 'Gmail'),
         ('outlook', 'Microsoft 365')],
        default='mailcow', required=True,
    )

    user_id = fields.Many2one(
        'res.users', string='Owner', ondelete='cascade',
        help="Leave empty to turn this into a shared mailbox managed through "
             "the Access tab.",
    )
    is_shared = fields.Boolean(compute='_compute_is_shared', store=True)
    access_ids = fields.One2many('mail.client.access', 'account_id', string='Access')
    # Flattened access lists. Record rules read these instead of walking through
    # the access model, which would recurse; one per permission level, because a
    # role that is only displayed and never enforced is a false promise.
    allowed_user_ids = fields.Many2many(
        'res.users', 'mail_client_account_allowed_user_rel', 'account_id', 'user_id',
        string='Can Read', copy=False, readonly=True,
    )
    allowed_writer_ids = fields.Many2many(
        'res.users', 'mail_client_account_allowed_writer_rel', 'account_id', 'user_id',
        string='Can Act', copy=False, readonly=True,
        help="Agents and managers: may flag, move, delete and reply.",
    )
    allowed_manager_ids = fields.Many2many(
        'res.users', 'mail_client_account_allowed_manager_rel', 'account_id', 'user_id',
        string='Can Manage', copy=False, readonly=True,
        help="Managers: may also change the mailbox and its access list.",
    )

    smtp_server_id = fields.Many2one(
        'ir.mail_server', string='Outgoing Mail Server',
        help="Overrides everything else for this mailbox. Leave empty to use the "
             "owner's personal outgoing server if they have one, and the mail "
             "server's shared one otherwise.",
    )
    smtp_source = fields.Char(
        string='Sending Via', compute='_compute_smtp_source',
        help="Which outgoing server this mailbox will actually use.",
    )

    server_auth_mode = fields.Selection(related='server_id.auth_mode', readonly=True)
    login = fields.Char(help="Only needed when the server uses per-account passwords.")
    password = fields.Char(
        groups='base.group_system',
        compute='_compute_password', inverse='_inverse_password',
    )
    password_encrypted = fields.Char(groups='base.group_system', copy=False, readonly=True)

    sync_mode = fields.Selection(
        [('one_way', 'Read only (server to Odoo)'),
         ('two_way', 'Two-way')],
        default='one_way', required=True,
        help="Two-way also pushes flags, tags, moves and deletes back to the "
             "mail server.",
    )
    sync_window_days = fields.Integer(
        string='Sync Window (days)', default=90,
        help="Messages older than this are not backfilled on the first sync. "
             "0 fetches everything - expect a long first run.",
    )
    active_sync = fields.Boolean(string='Automatic Sync', default=True)
    notify_token = fields.Char(
        readonly=True, copy=False, groups='base.group_system', index=True,
        help="Secret used by the mail server to trigger an immediate sync.",
    )
    notify_url = fields.Char(
        string='Push URL', compute='_compute_notify_url',
        groups='base.group_system',
        help="Call this from a Dovecot delivery script to sync within seconds "
             "instead of waiting for the cron.",
    )

    folder_ids = fields.One2many('mail.client.folder', 'account_id', string='Folders')
    tag_ids = fields.One2many('mail.client.tag', 'account_id', string='Tags')
    signature_ids = fields.One2many(
        'mail.client.signature', 'account_id', string='Signatures',
    )
    message_count = fields.Integer(compute='_compute_message_count')
    unread_count = fields.Integer(compute='_compute_unread_count')

    state = fields.Selection(
        [('draft', 'Not Connected'), ('connected', 'Connected'), ('error', 'Error')],
        default='draft', readonly=True, copy=False,
    )
    last_sync_date = fields.Datetime(readonly=True, copy=False)
    error_message = fields.Text(readonly=True, copy=False)

    _email_server_uniq = models.Constraint(
        'UNIQUE(email, server_id)',
        "This mailbox is already configured on that server.",
    )

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('user_id')
    def _compute_is_shared(self):
        for account in self:
            account.is_shared = not account.user_id

    @api.depends('notify_token', 'email')
    def _compute_notify_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for account in self:
            if account.notify_token:
                account.notify_url = '%s/mail_client/notify?token=%s&email=%s' % (
                    base, account.notify_token, account.email or '',
                )
            else:
                account.notify_url = False

    oauth_state = fields.Selection(
        [('none', 'Not applicable'),
         ('pending', 'Not authorised'),
         ('linked', 'Authorised')],
        compute='_compute_oauth_state',
        help="Whether this provider account has been signed into yet.",
    )

    @api.depends('account_type', 'google_gmail_refresh_token',
                 'microsoft_outlook_refresh_token')
    def _compute_oauth_state(self):
        for account in self:
            if account.account_type not in ('gmail', 'outlook'):
                account.oauth_state = 'none'
            else:
                account.oauth_state = 'linked' if account._oauth_ready() else 'pending'

    def action_authorise_oauth(self):
        """Hand off to the provider's consent screen.

        The heavy lifting - client id, CSRF token, callback - belongs to the
        core mixins, which already own the refresh token afterwards.
        """
        self.ensure_one()
        if self.account_type == 'gmail':
            return self.open_google_gmail_uri()
        if self.account_type == 'outlook':
            return self.open_microsoft_outlook_uri()
        raise UserError(_("This account type does not use OAuth2."))

    def action_revoke_oauth(self):
        self.ensure_one()
        values = {}
        if self.account_type == 'gmail':
            values = {
                'google_gmail_refresh_token': False,
                'google_gmail_access_token': False,
                'google_gmail_access_token_expiration': False,
            }
        elif self.account_type == 'outlook':
            values = {
                'microsoft_outlook_refresh_token': False,
                'microsoft_outlook_access_token': False,
                'microsoft_outlook_access_token_expiration': False,
            }
        if values:
            self.sudo().write(values)
        self.write({'state': 'draft'})
        return True

    def action_generate_notify_token(self):
        """Issue (or replace) the push token for this mailbox."""
        for account in self:
            account.sudo().notify_token = secrets.token_urlsafe(32)
        return True

    def action_revoke_notify_token(self):
        for account in self:
            account.sudo().notify_token = False
        return True

    def _recompute_allowed_users(self):
        """Rebuild the flattened access lists backing the record rules.

        This is deliberately an explicit rebuild rather than a stored compute:
        a stored compute did not reliably drop the row when an access line was
        deleted, which left a revoked user still able to see the mailbox. For
        fields that security depends on, being explicit beats being clever.
        """
        Access = self.env['mail.client.access'].sudo()
        for account in self:
            lines = Access.search([('account_id', '=', account.id)])
            writers = lines.filtered(lambda a: a.role in ('agent', 'manager'))
            managers = lines.filtered(lambda a: a.role == 'manager')
            account.sudo().write({
                'allowed_user_ids': [fields.Command.set(lines.user_id.ids)],
                'allowed_writer_ids': [fields.Command.set(writers.user_id.ids)],
                'allowed_manager_ids': [fields.Command.set(managers.user_id.ids)],
            })

    @api.depends('password_encrypted')
    def _compute_password(self):
        for account in self:
            account.password = PASSWORD_PLACEHOLDER if account.password_encrypted else False

    def _inverse_password(self):
        for account in self:
            if account.password == PASSWORD_PLACEHOLDER:
                continue
            account.password_encrypted = crypto.encrypt(account.password) if account.password else False

    @api.depends('folder_ids.message_ids')
    def _compute_message_count(self):
        counts = dict(self.env['mail.client.message']._read_group(
            [('account_id', 'in', self.ids)], ['account_id'], ['__count'],
        ))
        for account in self:
            account.message_count = counts.get(account, 0)

    @api.depends('folder_ids.message_ids.flag_seen')
    def _compute_unread_count(self):
        counts = dict(self.env['mail.client.message']._read_group(
            [('account_id', 'in', self.ids), ('flag_seen', '=', False)],
            ['account_id'], ['__count'],
        ))
        for account in self:
            account.unread_count = counts.get(account, 0)

    def _resolve_mail_server(self):
        """Pick the outgoing server for this mailbox.

        mailcow refuses to let one account send as another (Postfix's
        reject_sender_login_mismatch), so a single shared SMTP credential
        cannot serve several users. Odoo 19 already models this: a mail server
        with an ``owner_user_id`` is personal, is excluded from the pool used
        for ordinary Odoo notifications, and may only send as its owner.
        """
        self.ensure_one()
        if self.smtp_server_id:
            return self.smtp_server_id.sudo()
        if self.user_id:
            # Looked up directly rather than through res.users.
            # outgoing_mail_server_id: that field only depends on the user's
            # email, so it keeps a stale value when a personal server is
            # created afterwards in the same transaction.
            personal = self.env['ir.mail_server'].sudo().search([
                ('owner_user_id', '=', self.user_id.id),
            ], limit=1)
            if personal:
                return personal
        return self.server_id.sudo().smtp_server_id

    @api.depends('smtp_server_id', 'user_id', 'email', 'server_id.smtp_server_id')
    def _compute_smtp_source(self):
        for account in self:
            if not account.server_id and not account.smtp_server_id:
                account.smtp_source = False
                continue
            mail_server = account._resolve_mail_server()
            if not mail_server:
                account.smtp_source = _("Not configured - sending will fail")
                continue

            if account.smtp_server_id:
                source = _("%s (set on this mailbox)", mail_server.name)
            elif mail_server.owner_user_id:
                source = _("%(server)s (personal server of %(user)s)",
                           server=mail_server.name,
                           user=mail_server.owner_user_id.name)
            else:
                source = _("%s (fallback from the mail server)", mail_server.name)

            # Say now whether this will actually be accepted, rather than
            # letting the user find out from an SMTP rejection later.
            try:
                account._check_sender_allowed(mail_server)
            except UserError:
                source += _(" - WILL BE REJECTED: it is not allowed to send as %s",
                            account.email)
            account.smtp_source = source

    @api.model
    def _check_personal_server_wiring(self, mail_server):
        """Verify the three things Odoo requires of a personal mail server.

        res.users.outgoing_mail_server_id only recognises a server when
        from_filter, smtp_user *and* owner all point at the same person - the
        inner list in that domain is an AND, not an OR. Miss one and core
        refuses the server at send time with "the owner does not use it
        anymore", which describes neither the cause nor the fix.
        """
        owner = mail_server.owner_user_id
        if not owner:
            return

        owner_email = (owner.email or '').strip()
        if not owner_email:
            raise UserError(_(
                "'%(server)s' belongs to %(user)s, but that user has no email "
                "address in Odoo. Set it to the mailbox address first.",
                server=mail_server.name, user=owner.name,
            ))

        expected = email_normalize(owner_email)
        problems = []
        if email_normalize(mail_server.from_filter or '') != expected:
            problems.append(_("FROM Filtering is '%(actual)s'", actual=mail_server.from_filter or ''))
        if (mail_server.smtp_user or '').strip() != owner_email:
            problems.append(_("User email is '%(actual)s'", actual=mail_server.smtp_user or ''))
        if not problems:
            return

        raise UserError(_(
            "'%(server)s' is owned by %(user)s, whose Odoo email is "
            "'%(owner_email)s'. Odoo only treats a server as personal when its "
            "FROM Filtering and User email both match that address exactly.\n\n"
            "Mismatch: %(problems)s.\n\n"
            "Either change %(user)s's email in Odoo to the mailbox address, or "
            "point this server's FROM Filtering and User email at "
            "'%(owner_email)s'.",
            server=mail_server.name, user=owner.name, owner_email=owner_email,
            problems='; '.join(problems),
        ))

    def _check_sender_allowed(self, mail_server):
        """Refuse a send that the mail server is bound to reject.

        Failing here gives the address that is wrong; failing at SMTP gives a
        5.7.1 that names the *login* instead, which is much harder to act on.
        """
        self.ensure_one()
        mail_server = mail_server.sudo()
        self._check_personal_server_wiring(mail_server)

        from_filter = (mail_server.from_filter or '').strip()
        if not from_filter:
            if mail_server.owner_user_id:
                # Core refuses to let a personal server be forced without one,
                # with a message that says nothing about what to fix.
                raise UserError(_(
                    "'%(server)s' belongs to %(user)s but has no FROM Filtering, "
                    "so Odoo will not use it. Set its FROM Filtering to the "
                    "owner's address.",
                    server=mail_server.name, user=mail_server.owner_user_id.name,
                ))
            return
        own = (self.email or '').lower()
        allowed = [part.strip().lower() for part in from_filter.split(',') if part.strip()]
        for entry in allowed:
            if '@' in entry:
                if entry == own:
                    return
            elif own.endswith('@%s' % entry):
                return
        raise UserError(_(
            "'%(server)s' is only allowed to send as %(filter)s, but this mailbox "
            "is %(email)s.\n\n"
            "Give %(email)s its own outgoing server (Preferences > Account Security, "
            "or an ir.mail_server with this user as Owner), or widen the FROM "
            "Filtering on '%(server)s'.",
            server=mail_server.name, filter=from_filter, email=self.email,
        ))

    @api.onchange('server_id')
    def _onchange_server_id(self):
        if self.server_id:
            self.account_type = 'mailcow'

    # ------------------------------------------------------------------
    # sync
    # ------------------------------------------------------------------
    # Hosts are fixed for these providers, so there is nothing for an admin to
    # configure and nothing a mail.client.server record would usefully hold.
    OAUTH_HOSTS = {
        'gmail': ('imap.gmail.com', 993),
        'outlook': ('outlook.office365.com', 993),
    }

    @property
    def _email_field(self):
        """Field the OAuth mixins read the mailbox address from."""
        return 'email'

    def _oauth_ready(self):
        self.ensure_one()
        if self.account_type == 'gmail':
            return bool(self.sudo().google_gmail_refresh_token)
        if self.account_type == 'outlook':
            return bool(self.sudo().microsoft_outlook_refresh_token)
        return False

    def _open_oauth_connection(self):
        """Connect to Gmail or Microsoft 365 using the stored refresh token."""
        self.ensure_one()
        host, port = self.OAUTH_HOSTS[self.account_type]
        account = self.sudo()
        if self.account_type == 'gmail':
            auth_string = account._generate_oauth2_string(
                self.email, account.google_gmail_refresh_token)
        else:
            auth_string = account._generate_outlook_oauth2_string(self.email)

        connection = ImapConnection(
            host, port, 'ssl', self.email, None, oauth_string=auth_string,
        )
        connection.connect()
        return connection

    def _open_connection(self):
        self.ensure_one()
        if self.account_type in ('gmail', 'outlook') and not self.server_id:
            if not self._oauth_ready():
                raise UserError(_(
                    "'%(name)s' is not authorised yet.\n\n"
                    "Open the mailbox and click Authorise to sign in with "
                    "%(provider)s, or connect with an app password instead by "
                    "setting the account type to Generic IMAP.",
                    name=self.display_name,
                    provider=dict(self._fields['account_type'].selection).get(
                        self.account_type, self.account_type),
                ))
            return self._open_oauth_connection()

        if not self.server_id:
            if self.account_type in ('gmail', 'outlook'):
                host = 'imap.gmail.com' if self.account_type == 'gmail' \
                    else 'outlook.office365.com'
                raise UserError(_(
                    "'%(name)s' is set up as %(provider)s, which signs in with "
                    "OAuth2. That is not available yet.\n\n"
                    "You can connect today with an app password instead: set the "
                    "account type to Generic IMAP, and point it at a mail server "
                    "using %(host)s port 993 with SSL/TLS and 'Per-Account "
                    "Password' authentication.\n\n"
                    "Note that an outgoing SMTP server only covers sending; "
                    "reading the mailbox needs this IMAP connection.",
                    name=self.display_name,
                    provider=dict(self._fields['account_type'].selection).get(
                        self.account_type, self.account_type
                    ),
                    host=host,
                ))
            raise UserError(_(
                "'%s' has no mail server selected, so there is nothing to "
                "connect to.", self.display_name
            ))
        # mail.client.server is readable by system administrators only, but an
        # ordinary user still has to reach their own mailbox through it. The
        # sudo is on the server record alone; the audit entry written inside
        # _connect() still records the real user.
        return self.server_id.sudo()._connect(account=self.sudo())

    def action_sync_now(self):
        for account in self:
            account._sync()
        return True

    def _sync(self):
        """Synchronise one account. Never raises: failures are recorded."""
        self.ensure_one()
        connection = None
        try:
            connection = self._open_connection()
            # Outbox first, always. Pushing after the fetch would let a stale
            # server state overwrite what the user just did.
            self._push_pending_ops(connection)
            self._sync_folders(connection)
            folders = self.folder_ids.filtered(lambda f: f.subscribed and f.active)
            for folder in folders:
                folder._sync_messages(connection)
                # Commit per folder so a failure late in the run does not throw
                # away the folders that already succeeded. Same pattern as core
                # fetchmail. A test cursor refuses to commit outright, so a test
                # reaching this has to patch it - and must, because the except
                # below would otherwise swallow the refusal and pass.
                self.env.cr.commit()
            self.write({
                'state': 'connected',
                'error_message': False,
                'last_sync_date': fields.Datetime.now(),
            })
        except (ImapError, UserError) as exc:
            _logger.warning("Mail Client: sync failed for %s: %s", self.email, exc)
            self.write({'state': 'error', 'error_message': str(exc)})
        except Exception as exc:  # noqa: BLE001 - one bad account must not stop the cron
            _logger.exception("Mail Client: unexpected sync error for %s", self.email)
            # A database error leaves the cursor unusable, so the write below
            # would fail too and bury the original traceback under a second,
            # meaningless one. Roll back to the last per-folder commit first;
            # the folders already committed keep what they fetched.
            self.env.cr.rollback()
            self.write({'state': 'error', 'error_message': str(exc)})
        finally:
            if connection:
                connection.close()
        self._notify_bus()

    def _push_pending_ops(self, connection):
        """Send queued local changes to the server before fetching anything."""
        self.ensure_one()
        pending = self.env['mail.client.sync.op'].sudo().search([
            ('account_id', '=', self.id),
            ('state', '=', 'pending'),
        ])
        if not pending:
            return
        _logger.info("Mail Client: pushing %s pending operation(s) for %s",
                     len(pending), self.email)
        pending._push(connection)
        self.env['mail.client.message'].sudo().search([
            ('account_id', '=', self.id), ('is_dirty', '=', True),
        ]).write({'is_dirty': False})

    def _sync_folders(self, connection):
        """Reconcile the folder tree with the server."""
        self.ensure_one()
        Folder = self.env['mail.client.folder']
        remote = connection.list_folders()
        existing = {f.imap_path: f for f in self.folder_ids.with_context(active_test=False)}
        seen = set()

        # Parents first, so hierarchy links resolve in a single pass.
        for entry in sorted(remote, key=lambda e: e['path'].count(e['delimiter'] or '/')):
            path = entry['path']
            seen.add(path)
            role = self._detect_folder_role(path, entry['flags'])
            values = {
                'name': self._folder_display_name(path, entry['delimiter']),
                'imap_path': path,
                'delimiter': entry['delimiter'],
                'role': role,
                'active': True,
            }
            if role == 'inbox':
                # LSUB lists only explicitly subscribed mailboxes, and many
                # clients never subscribe INBOX because it always exists. A mail
                # client that skips the inbox is useless, so never let it off.
                values['subscribed'] = True

            folder = existing.get(path)
            if folder:
                # 'subscribed' is intentionally not refreshed from LSUB here:
                # after the first sync it belongs to the user, who may have
                # unticked a folder they do not want mirrored into Odoo.
                folder.write(values)
            else:
                values.setdefault('subscribed', entry['subscribed'])
                values.update({'account_id': self.id})
                folder = Folder.create(values)
                existing[path] = folder

            parent_path = self._parent_path(path, entry['delimiter'])
            parent = existing.get(parent_path) if parent_path else None
            if folder.parent_id != parent:
                folder.parent_id = parent

        # Folders removed on the server are archived, not deleted: their
        # messages may still be linked to Odoo records.
        stale = [f for path, f in existing.items() if path not in seen and f.active]
        for folder in stale:
            folder.active = False

    @staticmethod
    def _parent_path(path, delimiter):
        if not delimiter or delimiter not in path:
            return None
        return path.rsplit(delimiter, 1)[0]

    @staticmethod
    def _folder_display_name(path, delimiter):
        if delimiter and delimiter in path:
            return path.rsplit(delimiter, 1)[1]
        return path

    @staticmethod
    def _detect_folder_role(path, flags):
        for flag in flags:
            role = SPECIAL_USE_ROLES.get(flag.upper())
            if role:
                return role
        if path.upper() == 'INBOX':
            return 'inbox'
        leaf = path.rsplit('/', 1)[-1].rsplit('.', 1)[-1].strip().lower()
        return NAME_ROLES.get(leaf, 'other')

    def _notify_bus(self):
        """Push a refresh hint to everyone who can see this mailbox."""
        self.ensure_one()
        partners = (self.user_id | self.allowed_user_ids).partner_id
        if not partners:
            return
        partners._bus_send('mail_client.sync', {
            'account_id': self.id,
            'state': self.state,
            'last_sync_date': self.last_sync_date and fields.Datetime.to_string(self.last_sync_date),
        })

    @api.model
    def _syncable_accounts(self):
        """Accounts the cron is able to open.

        Gmail and Microsoft 365 accounts deliberately carry no ``server_id``:
        their host is fixed and a refresh token replaces the password, so there
        is nothing a mail.client.server record would usefully hold. Selecting on
        ``server_id`` alone therefore excluded every OAuth mailbox from the
        cron, and those accounts only ever synchronised when somebody pressed
        Sync Now by hand.

        Accounts that have not been authorised yet are left out as well: they
        cannot be opened, and retrying every two minutes would do nothing but
        overwrite ``error_message`` on a mailbox whose real problem is that
        nobody has signed into it.
        """
        accounts = self.search([
            ('active_sync', '=', True),
            '|', ('server_id', '!=', False),
                 ('account_type', 'in', ('gmail', 'outlook')),
        ])
        return accounts.filtered(lambda a: a.server_id or a._oauth_ready())

    @api.model
    def _cron_sync_all(self):
        for account in self._syncable_accounts():
            account._sync()
        return True

    def _folders_needing_structures(self):
        """Subscribed folders still holding messages nobody has described."""
        self.ensure_one()
        folders = self.folder_ids.filtered(lambda f: f.subscribed and f.active)
        if not folders:
            return folders.browse()
        groups = self.env['mail.client.message']._read_group(
            [('folder_id', 'in', folders.ids), ('structure_state', '=', 'unknown')],
            ['folder_id'],
        )
        return folders.browse([folder.id for (folder,) in groups])

    def _backfill_structures(self):
        """Describe stored messages whose MIME structure was never read.

        Runs apart from the sync so catching up on old mail never delays new
        mail. Like ``_sync`` it swallows its own failures: this is optional
        enrichment, and an account that cannot be reached will simply be
        further along next time.
        """
        self.ensure_one()
        folders = self._folders_needing_structures()
        if not folders:
            # The normal state once the catch-up is done. Checked before the
            # connection is opened, so a settled account costs one query every
            # quarter of an hour rather than a login and a SELECT per folder.
            return

        connection = None
        try:
            connection = self._open_connection()
            for folder in folders:
                connection.select(folder.imap_path, readonly=True)
                if folder._backfill_structures(connection):
                    self.env.cr.commit()
        except (ImapError, UserError) as exc:
            _logger.warning("Mail Client: structure backfill failed for %s: %s",
                            self.email, exc)
        except Exception:  # noqa: BLE001 - one bad account must not stop the cron
            _logger.exception("Mail Client: unexpected backfill error for %s", self.email)
        finally:
            if connection:
                connection.close()

    @api.model
    def _cron_backfill_structures(self):
        for account in self._syncable_accounts():
            account._backfill_structures()
        return True

    # ------------------------------------------------------------------
    # client action RPC
    # ------------------------------------------------------------------
    @api.model
    def _accessible_accounts(self):
        """Mailboxes belonging to the current user, or shared with them.

        Deliberately narrower than what the record rules permit. An
        administrator's rule is ``[(1, '=', 1)]`` so that they can configure
        other people's mailboxes, but that is a configuration privilege, not an
        invitation to read the mail: an unfiltered search here would open the
        Inbox on every user's private mailbox.

        Configuration still goes through the ordinary views under
        Configuration, which remain governed by the record rules.
        """
        return self.search([
            '|', ('user_id', '=', self.env.uid),
                 ('allowed_user_ids', 'in', [self.env.uid]),
        ])

    @api.model
    def get_inbox_state(self):
        """Return every mailbox the current user may open, with its folders."""
        accounts = self._accessible_accounts()
        if not accounts:
            return {'accounts': []}

        counts = self.env['mail.client.folder']._unread_by_folder(accounts.folder_ids.ids)
        payload = []
        for account in accounts:
            folders = account.folder_ids.filtered(lambda f: f.subscribed).sorted(
                key=lambda f: (f._role_rank(), f.name.lower())
            )
            payload.append({
                'id': account.id,
                'name': account.name,
                'email': account.email,
                'color': account.color,
                'state': account.state,
                'is_shared': account.is_shared,
                # Drives whether the interface offers move and delete at all.
                # The server refuses both on a read-only mailbox, so showing
                # the buttons would only ever produce an error dialog.
                'can_act': account.sync_mode == 'two_way',
                'error_message': account.error_message or '',
                'last_sync_date': account.last_sync_date and fields.Datetime.to_string(account.last_sync_date),
                'folders': [{
                    'id': folder.id,
                    'name': folder.name,
                    'role': folder.role,
                    'parent_id': folder.parent_id.id or False,
                    'unread': counts.get(folder.id, 0),
                } for folder in folders],
            })
        return {'accounts': payload}

    @api.model
    def sync_account(self, account_id):
        account = self.browse(account_id).exists()
        if not account:
            raise UserError(_("This mailbox no longer exists."))
        account.check_access('read')
        account.sudo()._sync()
        account.invalidate_recordset(['state', 'error_message'])
        return {'state': account.state, 'error_message': account.error_message or ''}
