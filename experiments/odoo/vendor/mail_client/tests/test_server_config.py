# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Server configuration guards.

A port/TLS mismatch surfaces as a bare socket timeout with no clue as to the
cause, so the cheapest fix is to stop it being configurable by accident.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools import config

from ..tools import crypto


@tagged('post_install', '-at_install')
class TestServerConfiguration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Credential encryption reads its key from odoo.conf, which a test run
        # has no reason to carry. Supply one for the duration of the class so
        # these tests do not depend on how the host happens to be configured.
        previous = config.options.get(crypto.CONFIG_KEY)
        config.options[crypto.CONFIG_KEY] = 'mail-client-unit-test-key'

        def restore():
            if previous is None:
                config.options.pop(crypto.CONFIG_KEY, None)
            else:
                config.options[crypto.CONFIG_KEY] = previous

        cls.addClassCleanup(restore)

        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow',
            'imap_host': 'mail.example.org',
            'imap_port': 993,
            'imap_encryption': 'ssl',
            'auth_mode': 'master',
            'master_user': 'master',
        })

    def test_port_993_forces_implicit_tls(self):
        with Form(self.server) as form:
            form.imap_encryption = 'starttls'
            form.imap_port = 993
        self.assertEqual(
            self.server.imap_encryption, 'ssl',
            "Port 993 speaks TLS from the first byte; STARTTLS there only times out.",
        )

    def test_port_143_switches_to_starttls(self):
        with Form(self.server) as form:
            form.imap_port = 143
        self.assertEqual(self.server.imap_encryption, 'starttls')

    def test_connect_without_account_is_refused(self):
        """The master user is not a mailbox, so there is nothing to log into."""
        with self.assertRaises(UserError):
            self.server._connect(account=None)

    def test_master_mode_requires_master_user(self):
        with self.assertRaises(ValidationError):
            self.env['mail.client.server'].create({
                'name': 'incomplete',
                'imap_host': 'mail.example.org',
                'auth_mode': 'master',
            })

    def test_master_login_uses_mailcow_separator(self):
        account = self.env['mail.client.account'].create({
            'name': 'Test',
            'email': 'user@example.org',
            'server_id': self.server.id,
        })
        self.server.master_password = 'secret'
        login, password = self.server._build_login(account)
        self.assertEqual(login, 'user@example.org*master@mailcow.local')
        self.assertEqual(password, 'secret')

    def test_master_password_is_never_exposed_in_clear(self):
        self.server.master_password = 'secret'
        stored = self.server.master_password_encrypted
        self.assertTrue(stored.startswith('fernet$'), "The password must be stored encrypted.")
        self.assertNotIn('secret', stored)

        # Drop the cache to read the field the way a later request would: the
        # compute must hand back a placeholder rather than the real secret.
        self.server.invalidate_recordset(['master_password'])
        self.assertNotEqual(
            self.server.master_password, 'secret',
            "Reading the field back must return a placeholder, not the secret.",
        )

    def test_saving_the_placeholder_keeps_the_stored_password(self):
        """Re-saving the form without touching the field must not wipe it."""
        self.server.master_password = 'secret'
        encrypted = self.server.master_password_encrypted
        self.server.invalidate_recordset(['master_password'])

        self.server.master_password = self.server.master_password  # placeholder round-trip
        self.assertEqual(self.server.master_password_encrypted, encrypted)
