# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Tags backed by IMAP keywords.

The point of doing this over IMAP rather than in a private Odoo table: a label
set here shows up in SOGo and on the phone, and one set there shows up here.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMailClientTags(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
        })
        cls.account = cls.env['mail.client.account'].create({
            'name': 'Test', 'email': 'test@example.org',
            'server_id': cls.server.id, 'sync_mode': 'two_way',
        })
        cls.folder = cls.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': cls.account.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })

    def _message(self, uid=1, **values):
        return self.env['mail.client.message'].create({
            'account_id': self.account.id, 'folder_id': self.folder.id,
            'imap_uid': uid, 'subject': 'Hello', **values,
        })

    def _ops(self):
        return self.env['mail.client.sync.op'].search([('account_id', '=', self.account.id)])

    # ------------------------------------------------------------------
    def test_system_flags_never_become_tags(self):
        Tag = self.env['mail.client.tag']
        keywords = Tag._keywords_from_flags(
            ['\\Seen', '\\Flagged', '\\Answered', '\\Draft', 'Penting']
        )
        self.assertEqual(
            keywords, ['Penting'],
            "Server-owned flags are mirrored onto boolean fields, not tags.",
        )

    def test_keyword_is_sanitised_for_the_protocol(self):
        Tag = self.env['mail.client.tag']
        self.assertEqual(Tag._sanitize_keyword('Perlu Tindak Lanjut'), 'Perlu_Tindak_Lanjut')
        self.assertEqual(Tag._sanitize_keyword('a(b)c'), 'a_b_c')

    def test_illegal_keyword_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['mail.client.tag'].create({
                'account_id': self.account.id,
                'name': 'Bad', 'imap_keyword': 'has space',
            })

    def test_known_labels_get_friendly_names(self):
        tag = self.env['mail.client.tag']._get_or_create(self.account, '$Label1')
        self.assertEqual(
            tag.name, 'Important',
            "Thunderbird's $Label1 should not be shown to users as '$Label1'.",
        )

    def test_keyword_from_server_creates_a_tag(self):
        values = self.folder._prepare_message_values({
            'uid': 5, 'flags': ['\\Seen', 'Penting'], 'size': 10,
            'subject': 'x', 'email_from': 'a@b.c', 'email_to': '', 'email_cc': '',
            'message_id': '<x@b.c>', 'in_reply_to': '', 'references': '',
            'date': False, 'spam_score': None, 'is_spam': False,
        })
        message = self.env['mail.client.message'].create({
            'account_id': self.account.id, 'folder_id': self.folder.id, **values,
        })
        self.assertEqual(message.tag_ids.imap_keyword, 'Penting')

    def test_tagging_queues_the_keyword(self):
        message = self._message()
        tag = self.env['mail.client.tag'].create({
            'account_id': self.account.id, 'name': 'Penting',
        })
        message._set_tag(tag, True)

        self.assertIn(tag, message.tag_ids)
        operation = self._ops()
        self.assertEqual(operation.op_type, 'set_flag')
        self.assertEqual(operation.payload['flags'], ['Penting'])

    def test_untagging_queues_a_removal(self):
        message = self._message()
        tag = self.env['mail.client.tag'].create({
            'account_id': self.account.id, 'name': 'Penting',
        })
        message._set_tag(tag, True)
        self._ops().unlink()

        message._set_tag(tag, False)
        self.assertNotIn(tag, message.tag_ids)
        self.assertEqual(self._ops().op_type, 'unset_flag')

    def test_tag_from_another_mailbox_is_refused(self):
        other = self.env['mail.client.account'].create({
            'name': 'Other', 'email': 'other@example.org', 'server_id': self.server.id,
        })
        tag = self.env['mail.client.tag'].create({
            'account_id': other.id, 'name': 'Foreign',
        })
        with self.assertRaises(UserError):
            self._message()._set_tag(tag, True)

    def test_labels_applied_elsewhere_are_picked_up(self):
        """A tag added in SOGo must appear here on the next sync."""
        message = self._message(uid=9)
        self.assertFalse(message.tag_ids)

        self.folder._apply_flag_changes([{'uid': 9, 'flags': ['\\Seen', 'Urgent']}])
        self.assertEqual(message.tag_ids.imap_keyword, 'Urgent')
        self.assertTrue(message.flag_seen)

    def test_labels_removed_elsewhere_disappear(self):
        message = self._message(uid=9)
        self.folder._apply_flag_changes([{'uid': 9, 'flags': ['Urgent']}])
        self.assertTrue(message.tag_ids)

        self.folder._apply_flag_changes([{'uid': 9, 'flags': []}])
        self.assertFalse(
            message.tag_ids,
            "Removing a label in another client must remove it here too.",
        )

    def test_one_way_account_does_not_push_tags(self):
        self.account.sync_mode = 'one_way'
        tag = self.env['mail.client.tag'].create({
            'account_id': self.account.id, 'name': 'Local',
        })
        self._message()._set_tag(tag, True)
        self.assertFalse(self._ops())
