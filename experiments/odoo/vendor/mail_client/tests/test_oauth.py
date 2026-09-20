# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""OAuth2 accounts.

Gmail and Microsoft 365 need no mail server record: the host is fixed and
there is no password, only a refresh token owned by Odoo's own mixins.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import config

from ..tools import crypto
from ..tools.imap_client import ImapConnection


@tagged('post_install', '-at_install')
class TestOAuthAccounts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Credential encryption reads its key from odoo.conf, which a test run
        # has no reason to carry.
        previous = config.options.get(crypto.CONFIG_KEY)
        config.options[crypto.CONFIG_KEY] = 'mail-client-unit-test-key'

        def restore():
            if previous is None:
                config.options.pop(crypto.CONFIG_KEY, None)
            else:
                config.options[crypto.CONFIG_KEY] = previous

        cls.addClassCleanup(restore)

        cls.Account = cls.env['mail.client.account']
        cls.gmail = cls.Account.create({
            'name': 'Gmail', 'email': 'user@gmail.com', 'account_type': 'gmail',
        })
        cls.outlook = cls.Account.create({
            'name': 'M365', 'email': 'user@contoso.com', 'account_type': 'outlook',
        })

    # ------------------------------------------------------------------
    def test_oauth_account_needs_no_mail_server(self):
        self.assertFalse(self.gmail.server_id)
        self.assertEqual(self.gmail.oauth_state, 'pending')

    def test_unauthorised_account_explains_what_to_do(self):
        with self.assertRaises(UserError) as caught:
            self.gmail._open_connection()
        message = str(caught.exception)
        self.assertIn('not authorised', message)
        self.assertIn('Generic IMAP', message)

    def test_state_flips_once_a_token_exists(self):
        self.gmail.sudo().google_gmail_refresh_token = 'refresh-token'
        self.gmail.invalidate_recordset(['oauth_state'])
        self.assertEqual(self.gmail.oauth_state, 'linked')
        self.assertTrue(self.gmail._oauth_ready())

    def test_revoking_clears_the_token(self):
        self.gmail.sudo().google_gmail_refresh_token = 'refresh-token'
        self.gmail.action_revoke_oauth()
        self.assertFalse(self.gmail.sudo().google_gmail_refresh_token)
        self.gmail.invalidate_recordset(['oauth_state'])
        self.assertEqual(self.gmail.oauth_state, 'pending')

    def test_hosts_are_fixed_per_provider(self):
        self.assertEqual(self.Account.OAUTH_HOSTS['gmail'], ('imap.gmail.com', 993))
        self.assertEqual(
            self.Account.OAUTH_HOSTS['outlook'], ('outlook.office365.com', 993))

    def test_gmail_connection_uses_xoauth2(self):
        """No password is ever sent; LOGIN is replaced by XOAUTH2."""
        self.gmail.sudo().google_gmail_refresh_token = 'refresh-token'
        captured = {}

        def fake_connect(self_conn, authenticate=True):
            captured['host'] = self_conn.host
            captured['port'] = self_conn.port
            captured['oauth'] = self_conn.oauth_string
            captured['password'] = self_conn.password
            return self_conn

        with patch.object(type(self.gmail), '_generate_oauth2_string',
                          lambda self, user, token: 'user=%s^Aauth=Bearer x^A^A' % user), \
             patch.object(ImapConnection, 'connect', fake_connect):
            self.gmail._open_oauth_connection()

        self.assertEqual(captured['host'], 'imap.gmail.com')
        self.assertEqual(captured['port'], 993)
        self.assertIn('user@gmail.com', captured['oauth'])
        self.assertIsNone(captured['password'])

    def test_outlook_connection_uses_its_own_host(self):
        self.outlook.sudo().microsoft_outlook_refresh_token = 'refresh-token'
        captured = {}

        def fake_connect(self_conn, authenticate=True):
            captured['host'] = self_conn.host
            captured['oauth'] = self_conn.oauth_string
            return self_conn

        with patch.object(type(self.outlook), '_generate_outlook_oauth2_string',
                          lambda self, login: 'user=%s^Aauth=Bearer y^A^A' % login), \
             patch.object(ImapConnection, 'connect', fake_connect):
            self.outlook._open_oauth_connection()

        self.assertEqual(captured['host'], 'outlook.office365.com')
        self.assertIn('user@contoso.com', captured['oauth'])

    def test_authorise_is_refused_for_non_oauth_accounts(self):
        server = self.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
        })
        account = self.Account.create({
            'name': 'Self hosted', 'email': 'me@example.org',
            'account_type': 'mailcow', 'server_id': server.id,
        })
        with self.assertRaises(UserError):
            account.action_authorise_oauth()

    def test_app_password_route_still_works_for_gmail(self):
        """Generic IMAP against Gmail must keep working alongside OAuth."""
        server = self.env['mail.client.server'].create({
            'name': 'Gmail', 'imap_host': 'imap.gmail.com', 'imap_port': 993,
            'imap_encryption': 'ssl', 'auth_mode': 'per_account',
        })
        account = self.Account.create({
            'name': 'Gmail app password', 'email': 'other@gmail.com',
            'account_type': 'imap', 'server_id': server.id,
            'login': 'other@gmail.com',
        })
        account.password = 'app-password'
        login, password = server._build_login(account)
        self.assertEqual(login, 'other@gmail.com')
        self.assertEqual(password, 'app-password')
