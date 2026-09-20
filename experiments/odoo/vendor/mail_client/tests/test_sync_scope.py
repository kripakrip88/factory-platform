# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Which mailboxes the cron picks up, and which ones the inbox shows.

Two rules are defended here:

* the cron must reach every account it is *able* to open, including Gmail and
  Microsoft 365, which deliberately carry no mail server record;
* the inbox must show a user their own and their shared mailboxes, and nothing
  else - not even for an administrator, whose record rule permits everything so
  that they can configure other people's accounts.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSyncableAccounts(TransactionCase):
    """The cron's account selection.

    A Gmail account has no server_id: its host is fixed and a refresh token
    replaces the password. Selecting on server_id alone excluded every OAuth
    mailbox, which then only synced when somebody pressed Sync Now by hand.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
        })
        cls.self_hosted = cls.env['mail.client.account'].create({
            'name': 'Self hosted', 'email': 'self@example.org',
            'server_id': cls.server.id,
        })

    def _gmail(self, email='someone@gmail.com', linked=True, **values):
        account = self.env['mail.client.account'].create({
            'name': 'Gmail', 'email': email, 'account_type': 'gmail', **values,
        })
        if linked:
            account.sudo().google_gmail_refresh_token = 'refresh-token'
        return account

    def _syncable(self):
        return self.env['mail.client.account']._syncable_accounts()

    # ------------------------------------------------------------------
    def test_authorised_gmail_is_picked_up(self):
        account = self._gmail()
        self.assertIn(
            account, self._syncable(),
            "A linked Gmail mailbox has no server_id and was skipped by the "
            "cron, so it only ever synced when Sync Now was pressed.",
        )

    def test_authorised_outlook_is_picked_up(self):
        account = self.env['mail.client.account'].create({
            'name': 'M365', 'email': 'someone@contoso.com', 'account_type': 'outlook',
        })
        account.sudo().microsoft_outlook_refresh_token = 'refresh-token'
        self.assertIn(account, self._syncable())

    def test_self_hosted_account_is_still_picked_up(self):
        self.assertIn(self.self_hosted, self._syncable())

    def test_unauthorised_gmail_is_left_alone(self):
        account = self._gmail(email='never@gmail.com', linked=False)
        self.assertNotIn(
            account, self._syncable(),
            "An account nobody has signed into cannot be opened; retrying every "
            "two minutes would only overwrite error_message.",
        )

    def test_automatic_sync_is_still_honoured(self):
        account = self._gmail(email='paused@gmail.com', active_sync=False)
        self.assertNotIn(account, self._syncable())

    def test_both_crons_use_the_same_selection(self):
        """The backfill had the same server_id filter, and the same blind spot."""
        account = self._gmail(email='backfill@gmail.com')
        calls = []
        self.patch(
            type(account), '_backfill_structures',
            lambda records: calls.extend(records.ids),
        )
        self.env['mail.client.account']._cron_backfill_structures()
        self.assertIn(account.id, calls)


@tagged('post_install', '-at_install')
class TestInboxScope(TransactionCase):
    """What the three-pane inbox lists.

    The administrator rule is [(1, '=', 1)] so that configuration works. That
    is a configuration privilege, not permission to read the mail, so the inbox
    asks a narrower question than the record rules would answer.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
        })
        internal = cls.env.ref('base.group_user')
        cls.admin_user = cls.env['res.users'].create({
            'name': 'Mail Admin', 'login': 'mail-admin@example.org',
            'email': 'mail-admin@example.org',
            'group_ids': [(6, 0, [
                cls.env.ref('mail_client.group_mail_client_admin').id, internal.id,
            ])],
        })
        cls.other_user = cls.env['res.users'].create({
            'name': 'Someone Else', 'login': 'someone-else@example.org',
            'email': 'someone-else@example.org',
            'group_ids': [(6, 0, [
                cls.env.ref('mail_client.group_mail_client_user').id, internal.id,
            ])],
        })
        cls.admin_mailbox = cls.env['mail.client.account'].create({
            'name': 'Admin mailbox', 'email': 'mail-admin@example.org',
            'server_id': cls.server.id, 'user_id': cls.admin_user.id,
        })
        cls.private_mailbox = cls.env['mail.client.account'].create({
            'name': 'Private', 'email': 'someone-else@example.org',
            'server_id': cls.server.id, 'user_id': cls.other_user.id,
        })
        cls.shared_mailbox = cls.env['mail.client.account'].create({
            'name': 'Sales', 'email': 'sales@example.org',
            'server_id': cls.server.id,
        })

    def _inbox_account_ids(self, user):
        state = self.env['mail.client.account'].with_user(user).get_inbox_state()
        return {entry['id'] for entry in state['accounts']}

    # ------------------------------------------------------------------
    def test_admin_does_not_see_another_users_private_mailbox(self):
        self.assertNotIn(
            self.private_mailbox.id, self._inbox_account_ids(self.admin_user),
            "Configuring other people's mailboxes must not mean reading their "
            "mail from the inbox.",
        )

    def test_admin_sees_their_own_mailbox(self):
        self.assertIn(self.admin_mailbox.id, self._inbox_account_ids(self.admin_user))

    def test_shared_access_is_listed(self):
        self.env['mail.client.access'].create({
            'account_id': self.shared_mailbox.id,
            'user_id': self.admin_user.id,
            'role': 'agent',
        })
        self.assertIn(self.shared_mailbox.id, self._inbox_account_ids(self.admin_user))

    def test_shared_mailbox_without_access_is_not_listed(self):
        self.assertNotIn(
            self.shared_mailbox.id, self._inbox_account_ids(self.admin_user),
            "A shared mailbox is only shared with the users on its Access tab.",
        )

    def test_ordinary_user_sees_only_their_own(self):
        self.assertEqual(
            self._inbox_account_ids(self.other_user), {self.private_mailbox.id},
        )

    def test_read_only_mailbox_is_reported_as_such(self):
        """The client hides move and delete on a read-only mailbox."""
        state = self.env['mail.client.account'].with_user(
            self.other_user).get_inbox_state()
        entry = next(e for e in state['accounts'] if e['id'] == self.private_mailbox.id)
        self.assertFalse(entry['can_act'], "one_way is the default sync mode.")

        self.private_mailbox.sync_mode = 'two_way'
        state = self.env['mail.client.account'].with_user(
            self.other_user).get_inbox_state()
        entry = next(e for e in state['accounts'] if e['id'] == self.private_mailbox.id)
        self.assertTrue(entry['can_act'])
