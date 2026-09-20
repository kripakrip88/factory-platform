# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Conversation grouping, signatures, contact context and the unified inbox."""
from datetime import datetime

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPackageB(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
        })
        cls.account = cls.env['mail.client.account'].create({
            'name': 'Test', 'email': 'me@example.org', 'server_id': cls.server.id,
        })
        cls.inbox = cls.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': cls.account.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })
        cls.Message = cls.env['mail.client.message']

    def _message(self, uid, subject, thread_key, day, seen=True, sender='a@b.com',
                 folder=None, message_id=None, account=None):
        return self.Message.create({
            'account_id': (account or self.account).id,
            'folder_id': (folder or self.inbox).id,
            'imap_uid': uid, 'subject': subject, 'thread_key': thread_key,
            'email_from': sender, 'flag_seen': seen, 'message_id': message_id,
            'date': datetime(2026, 8, day, 10, 0, 0),
        })

    def _folder(self, name, role='other', account=None):
        return self.env['mail.client.folder'].create({
            'name': name, 'account_id': (account or self.account).id,
            'imap_path': name, 'role': role,
        })

    # ------------------------------------------------------------------
    # threading
    # ------------------------------------------------------------------
    def test_thread_key_never_empty(self):
        """A NULL key would collapse unrelated mail into one fake conversation."""
        key = self.Message._compute_thread_key_value({
            'references': '', 'in_reply_to': '', 'message_id': '', 'uid': 77,
        })
        self.assertTrue(key)
        self.assertIn('77', key)

    def test_replies_collapse_into_one_row(self):
        self._message(1, 'Quotation', '<root@x>', 1)
        self._message(2, 'Re: Quotation', '<root@x>', 2)
        self._message(3, 'Re: Quotation', '<root@x>', 3)
        self._message(4, 'Unrelated', '<other@x>', 4)

        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        self.assertEqual(len(result['messages']), 2)
        by_key = {row['thread_key']: row for row in result['messages']}
        self.assertEqual(by_key['<root@x>']['thread_count'], 3)
        self.assertEqual(by_key['<other@x>']['thread_count'], 1)

    def test_conversation_row_shows_the_latest_message(self):
        self._message(1, 'First', '<root@x>', 1)
        self._message(2, 'Latest', '<root@x>', 5)
        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        self.assertEqual(result['messages'][0]['subject'], 'Latest')

    def test_conversation_is_unread_while_any_message_is(self):
        self._message(1, 'First', '<root@x>', 1, seen=True)
        self._message(2, 'Reply', '<root@x>', 2, seen=False)
        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        row = result['messages'][0]
        self.assertFalse(row['flag_seen'])
        self.assertEqual(row['unread_count'], 1)

    def test_flat_mode_still_lists_every_message(self):
        self._message(1, 'First', '<root@x>', 1)
        self._message(2, 'Reply', '<root@x>', 2)
        result = self.env['mail.client.folder'].get_messages(folder_id=self.inbox.id)
        self.assertEqual(len(result['messages']), 2)
        self.assertFalse(result['threaded'])

    def test_get_thread_returns_members_oldest_first(self):
        first = self._message(1, 'First', '<root@x>', 1)
        self._message(2, 'Reply', '<root@x>', 3)
        thread = self.Message.get_thread(first.id)
        self.assertEqual([row['subject'] for row in thread], ['First', 'Reply'])

    # ------------------------------------------------------------------
    # a conversation spans folders: the reply lives in Sent
    # ------------------------------------------------------------------
    def test_reply_in_sent_counts_towards_the_inbox_conversation(self):
        """Counted per folder, every exchange looks like two lone messages."""
        sent = self._folder('Sent', role='sent')
        self._message(1, 'Quotation please', '<root@x>', 1)
        self._message(1, 'Re: Quotation please', '<root@x>', 2, folder=sent)

        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        self.assertEqual(len(result['messages']), 1)
        self.assertEqual(result['messages'][0]['thread_count'], 2)

    def test_conversation_row_stays_inside_the_folder_being_viewed(self):
        """Acting on a row must not reach into Sent behind the user's back."""
        sent = self._folder('Sent', role='sent')
        inbox_message = self._message(1, 'Quotation please', '<root@x>', 1)
        self._message(1, 'Re: Quotation please', '<root@x>', 9, folder=sent)

        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        row = result['messages'][0]
        self.assertEqual(row['id'], inbox_message.id)
        self.assertEqual(row['subject'], 'Quotation please')
        # ...while still reporting the true size of the conversation
        self.assertEqual(row['thread_count'], 2)

    def test_thread_count_does_not_leak_across_accounts(self):
        """Two mailboxes on one mailing list share a thread key, not a thread."""
        other = self.env['mail.client.account'].create({
            'name': 'Second', 'email': 'two@example.org', 'server_id': self.server.id,
        })
        other_inbox = self._folder('INBOX', role='inbox', account=other)
        self._message(1, 'Newsletter', '<list@x>', 1)
        self._message(1, 'Newsletter', '<list@x>', 1,
                      folder=other_inbox, account=other)

        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        self.assertEqual(result['messages'][0]['thread_count'], 1)

    # ------------------------------------------------------------------
    # Gmail lists every message twice: INBOX and [Gmail]/All Mail
    # ------------------------------------------------------------------
    def test_gmail_duplicate_is_counted_once(self):
        all_mail = self._folder('[Gmail]/All Mail', role='archive')
        self._message(1, 'Hello', '<root@x>', 1, message_id='<same@gmail>')
        self._message(1, 'Hello', '<root@x>', 1,
                      folder=all_mail, message_id='<same@gmail>')

        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        self.assertEqual(result['messages'][0]['thread_count'], 1)

    def test_gmail_duplicate_is_not_shown_twice_in_a_thread(self):
        all_mail = self._folder('[Gmail]/All Mail', role='archive')
        original = self._message(1, 'Hello', '<root@x>', 1, message_id='<same@gmail>')
        self._message(1, 'Hello', '<root@x>', 1,
                      folder=all_mail, message_id='<same@gmail>')

        thread = self.Message.get_thread(original.id)
        self.assertEqual(len(thread), 1)

    def test_a_real_archive_folder_is_not_treated_as_a_duplicate(self):
        """Dovecot's Archive holds distinct messages, unlike Gmail's All Mail."""
        archive = self._folder('Archive', role='archive')
        self._message(1, 'Question', '<root@x>', 1, message_id='<one@example.org>')
        self._message(1, 'Re: Question', '<root@x>', 2,
                      folder=archive, message_id='<two@example.org>')

        result = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)
        self.assertEqual(result['messages'][0]['thread_count'], 2)

    # ------------------------------------------------------------------
    # unified inbox
    # ------------------------------------------------------------------
    def test_unified_inbox_spans_accounts(self):
        second = self.env['mail.client.account'].create({
            'name': 'Second', 'email': 'two@example.org', 'server_id': self.server.id,
        })
        other_inbox = self.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': second.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })
        self._message(1, 'From one', '<a@x>', 1)
        self.Message.create({
            'account_id': second.id, 'folder_id': other_inbox.id, 'imap_uid': 1,
            'subject': 'From two', 'thread_key': '<b@x>',
            'date': datetime(2026, 8, 2, 10, 0, 0),
        })

        result = self.env['mail.client.folder'].get_messages(unified=True)
        subjects = {row['subject'] for row in result['messages']}
        self.assertEqual(subjects, {'From one', 'From two'})

    def test_unified_inbox_ignores_other_folders(self):
        sent = self.env['mail.client.folder'].create({
            'name': 'Sent', 'account_id': self.account.id,
            'imap_path': 'Sent', 'role': 'sent',
        })
        self._message(1, 'In inbox', '<a@x>', 1)
        self.Message.create({
            'account_id': self.account.id, 'folder_id': sent.id, 'imap_uid': 2,
            'subject': 'In sent', 'thread_key': '<b@x>',
            'date': datetime(2026, 8, 2, 10, 0, 0),
        })
        result = self.env['mail.client.folder'].get_messages(unified=True)
        self.assertEqual([row['subject'] for row in result['messages']], ['In inbox'])

    # ------------------------------------------------------------------
    # signatures
    # ------------------------------------------------------------------
    def test_signature_is_inserted_on_a_new_message(self):
        self.env['mail.client.signature'].create({
            'account_id': self.account.id, 'name': 'Default',
            'body_html': '<p>Regards,<br/>Irwan</p>', 'is_default': True,
        })
        payload = self.env['mail.client.compose'].start(self.account.id)
        self.assertIn('Regards', payload['body_html'])

    def test_signature_can_be_skipped_on_replies(self):
        self.env['mail.client.signature'].create({
            'account_id': self.account.id, 'name': 'Default',
            'body_html': '<p>Regards</p>', 'is_default': True,
            'use_on_reply': False,
        })
        parent = self._message(1, 'Ask', '<root@x>', 1)
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='reply', message_id=parent.id)
        self.assertNotIn('Regards', payload['body_html'])

    def test_signature_sits_above_the_quoted_original(self):
        self.env['mail.client.signature'].create({
            'account_id': self.account.id, 'name': 'Default',
            'body_html': '<p>Regards</p>', 'is_default': True,
        })
        parent = self._message(1, 'Ask', '<root@x>', 1)
        parent.write({'body_html': '<p>Original text</p>', 'body_state': 'fetched',
                      'structure_state': 'parsed'})
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='reply', message_id=parent.id)
        self.assertLess(
            payload['body_html'].index('Regards'),
            payload['body_html'].index('Original text'),
            "Nobody signs below the message they are replying to.",
        )

    def test_only_one_signature_stays_default(self):
        Signature = self.env['mail.client.signature']
        first = Signature.create({
            'account_id': self.account.id, 'name': 'A', 'is_default': True,
        })
        Signature.create({
            'account_id': self.account.id, 'name': 'B', 'is_default': True,
        })
        self.assertFalse(first.is_default)

    # ------------------------------------------------------------------
    # contact context
    # ------------------------------------------------------------------
    def test_contact_context_counts_history(self):
        self._message(1, 'One', '<a@x>', 1, sender='"Budi" <budi@customer.co.id>')
        current = self._message(2, 'Two', '<b@x>', 2, sender='budi@customer.co.id')
        context = self.Message.get_contact_context(current.id)
        self.assertEqual(context['email'], 'budi@customer.co.id')
        self.assertEqual(context['message_count'], 2)
        self.assertEqual(len(context['history']), 1)

    def test_contact_context_without_a_known_partner(self):
        message = self._message(1, 'One', '<a@x>', 1, sender='stranger@nowhere.io')
        context = self.Message.get_contact_context(message.id)
        self.assertIsNone(context['partner'])
        self.assertEqual(context['email'], 'stranger@nowhere.io')

    def test_contact_context_links_a_known_partner(self):
        self.env['res.partner'].create({
            'name': 'Budi Santoso', 'email': 'budi@customer.co.id',
        })
        message = self._message(1, 'One', '<a@x>', 1, sender='budi@customer.co.id')
        context = self.Message.get_contact_context(message.id)
        self.assertTrue(context['partner'])
        self.assertEqual(context['partner']['name'], 'Budi Santoso')
