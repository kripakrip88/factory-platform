# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Record rule coverage.

Leaking one person's mail to another is the most expensive bug this module
could ship, so the rules get their own test suite rather
than being trusted to review.
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMailClientAccessRights(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        group_user = cls.env.ref('mail_client.group_mail_client_user')
        group_agent = cls.env.ref('mail_client.group_mail_client_agent')
        group_admin = cls.env.ref('mail_client.group_mail_client_admin')

        cls.alice = Users.create({
            'name': 'Alice', 'login': 'mc_alice', 'email': 'alice@example.org',
            'group_ids': [(6, 0, [group_user.id, cls.env.ref('base.group_user').id])],
        })
        cls.bob = Users.create({
            'name': 'Bob', 'login': 'mc_bob', 'email': 'bob@example.org',
            'group_ids': [(6, 0, [group_agent.id, cls.env.ref('base.group_user').id])],
        })
        cls.manager = Users.create({
            'name': 'Manager', 'login': 'mc_manager', 'email': 'manager@example.org',
            'group_ids': [(6, 0, [group_admin.id, cls.env.ref('base.group_user').id])],
        })

        cls.server = cls.env['mail.client.server'].create({
            'name': 'Test mailcow',
            'imap_host': 'mail.example.org',
            'auth_mode': 'master',
            'master_user': 'master',
        })

        cls.alice_account = cls._make_account('Alice Inbox', 'alice@example.org', cls.alice)
        cls.bob_account = cls._make_account('Bob Inbox', 'bob@example.org', cls.bob)
        cls.shared_account = cls._make_account('Sales', 'sales@example.org', user=False)

        cls.env['mail.client.access'].create({
            'account_id': cls.shared_account.id,
            'user_id': cls.bob.id,
            'role': 'agent',
        })

    @classmethod
    def _make_account(cls, name, email, user=False):
        account = cls.env['mail.client.account'].create({
            'name': name,
            'email': email,
            'server_id': cls.server.id,
            'user_id': user.id if user else False,
        })
        folder = cls.env['mail.client.folder'].create({
            'name': 'INBOX',
            'account_id': account.id,
            'imap_path': 'INBOX',
            'role': 'inbox',
        })
        cls.env['mail.client.message'].create({
            'account_id': account.id,
            'folder_id': folder.id,
            'imap_uid': 1,
            'subject': 'Secret of %s' % email,
            'email_from': 'someone@example.org',
        })
        return account

    # ------------------------------------------------------------------
    def test_own_account_visible(self):
        accounts = self.env['mail.client.account'].with_user(self.alice).search([])
        self.assertIn(self.alice_account, accounts)

    def test_other_user_account_hidden(self):
        accounts = self.env['mail.client.account'].with_user(self.alice).search([])
        self.assertNotIn(
            self.bob_account, accounts,
            "Alice must not see Bob's mailbox.",
        )

    def test_other_user_messages_hidden(self):
        messages = self.env['mail.client.message'].with_user(self.alice).search([])
        self.assertFalse(
            messages.filtered(lambda m: m.account_id == self.bob_account),
            "Alice must not see any message belonging to Bob.",
        )

    def test_other_user_folders_hidden(self):
        folders = self.env['mail.client.folder'].with_user(self.alice).search([])
        self.assertFalse(
            folders.filtered(lambda f: f.account_id == self.bob_account),
            "Alice must not see any folder belonging to Bob.",
        )

    def test_direct_read_of_foreign_message_is_refused(self):
        """Bypassing search must not bypass the rule."""
        message = self.bob_account.folder_ids.message_ids[0]
        with self.assertRaises(AccessError):
            message.with_user(self.alice).check_access('read')

    def test_shared_mailbox_visible_to_granted_user(self):
        accounts = self.env['mail.client.account'].with_user(self.bob).search([])
        self.assertIn(
            self.shared_account, accounts,
            "Bob was granted access to the shared mailbox and should see it.",
        )

    def test_shared_mailbox_hidden_from_others(self):
        accounts = self.env['mail.client.account'].with_user(self.alice).search([])
        self.assertNotIn(
            self.shared_account, accounts,
            "Alice has no access entry, so the shared mailbox must stay hidden.",
        )

    def test_revoking_access_hides_shared_mailbox(self):
        access = self.env['mail.client.access'].search([
            ('account_id', '=', self.shared_account.id),
            ('user_id', '=', self.bob.id),
        ])
        access.unlink()
        accounts = self.env['mail.client.account'].with_user(self.bob).search([])
        self.assertNotIn(
            self.shared_account, accounts,
            "Removing the access entry must immediately revoke visibility.",
        )

    # ------------------------------------------------------------------
    # shared mailbox roles
    # ------------------------------------------------------------------
    def _shared_message(self):
        return self.shared_account.folder_ids.message_ids[0]

    def _grant(self, user, role):
        access = self.env['mail.client.access'].search([
            ('account_id', '=', self.shared_account.id), ('user_id', '=', user.id),
        ])
        if access:
            access.role = role
        else:
            self.env['mail.client.access'].create({
                'account_id': self.shared_account.id,
                'user_id': user.id, 'role': role,
            })

    def test_viewer_can_read_the_shared_mailbox(self):
        self._grant(self.alice, 'viewer')
        messages = self.env['mail.client.message'].with_user(self.alice).search([])
        self.assertTrue(messages.filtered(lambda m: m.account_id == self.shared_account))

    def test_viewer_cannot_change_a_message(self):
        """A viewer that can delete mail is not a viewer."""
        self._grant(self.alice, 'viewer')
        message = self._shared_message()
        with self.assertRaises(AccessError):
            message.with_user(self.alice).write({'flag_seen': True})

    def test_viewer_cannot_delete_a_message(self):
        self._grant(self.alice, 'viewer')
        message = self._shared_message()
        with self.assertRaises(AccessError):
            message.with_user(self.alice).unlink()

    def test_agent_can_act_on_messages(self):
        self._grant(self.alice, 'agent')
        message = self._shared_message()
        message.with_user(self.alice).write({'flag_seen': True})
        self.assertTrue(message.flag_seen)

    def test_agent_cannot_reconfigure_the_mailbox(self):
        self._grant(self.alice, 'agent')
        with self.assertRaises(AccessError):
            self.shared_account.with_user(self.alice).write({'sync_window_days': 5})

    def test_manager_can_reconfigure_the_mailbox(self):
        self._grant(self.alice, 'manager')
        self.shared_account.with_user(self.alice).write({'sync_window_days': 5})
        self.assertEqual(self.shared_account.sync_window_days, 5)

    def test_role_change_takes_effect_immediately(self):
        self._grant(self.alice, 'viewer')
        message = self._shared_message()
        with self.assertRaises(AccessError):
            message.with_user(self.alice).write({'flag_flagged': True})

        self._grant(self.alice, 'agent')
        message.with_user(self.alice).write({'flag_flagged': True})
        self.assertTrue(message.flag_flagged)

    def test_owner_is_unaffected_by_roles(self):
        message = self.alice_account.folder_ids.message_ids[0]
        message.with_user(self.alice).write({'flag_seen': True})
        self.assertTrue(message.flag_seen)

    def test_admin_sees_everything(self):
        accounts = self.env['mail.client.account'].with_user(self.manager).search([])
        self.assertIn(self.alice_account, accounts)
        self.assertIn(self.bob_account, accounts)
        self.assertIn(self.shared_account, accounts)

    def test_server_credentials_hidden_from_mail_admin(self):
        """Mail Client admins manage mailboxes; they are not system admins."""
        with self.assertRaises(AccessError):
            self.env['mail.client.server'].with_user(self.manager).search([])

    def test_get_inbox_state_respects_rules(self):
        state = self.env['mail.client.account'].with_user(self.alice).get_inbox_state()
        emails = {a['email'] for a in state['accounts']}
        self.assertEqual(emails, {'alice@example.org'})

    def test_get_inbox_state_includes_shared_for_agent(self):
        state = self.env['mail.client.account'].with_user(self.bob).get_inbox_state()
        emails = {a['email'] for a in state['accounts']}
        self.assertEqual(emails, {'bob@example.org', 'sales@example.org'})

    def test_audit_log_is_append_only(self):
        entry = self.env['mail.client.audit'].log_access(
            server=self.server, account=self.alice_account,
        )
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            entry.write({'detail': 'tampered'})
        with self.assertRaises(UserError):
            entry.unlink()
