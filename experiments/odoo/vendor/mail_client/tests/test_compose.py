# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Composing and sending.

The parts worth defending: threading headers (get them wrong and every reply
starts a new conversation in every other client, including the archive), and
filing a copy in Sent so the message is not visible only inside Odoo.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCompose(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mail_server = cls.env['ir.mail_server'].create({
            'name': 'mailcow smtp',
            'smtp_host': 'mail.example.org',
            'smtp_port': 587,
            'smtp_encryption': 'starttls',
        })
        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
            'smtp_server_id': cls.mail_server.id,
        })
        cls.account = cls.env['mail.client.account'].create({
            'name': 'Test', 'email': 'me@example.org', 'server_id': cls.server.id,
        })
        cls.inbox = cls.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': cls.account.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })
        cls.sent = cls.env['mail.client.folder'].create({
            'name': 'Sent', 'account_id': cls.account.id,
            'imap_path': 'Sent', 'role': 'sent',
        })
        cls.parent = cls.env['mail.client.message'].create({
            'account_id': cls.account.id,
            'folder_id': cls.inbox.id,
            'imap_uid': 1,
            'subject': 'Quotation request',
            'email_from': '"Budi" <budi@customer.co.id>',
            'email_to': 'me@example.org, sales@example.org',
            'email_cc': 'boss@customer.co.id',
            'message_id': '<original@customer.co.id>',
            'references': '<older@customer.co.id>',
            'body_html': '<p>Please send a quotation.</p>',
            'body_state': 'fetched',
        })

    def _draft(self, **values):
        return self.env['mail.client.compose'].create({
            'account_id': self.account.id,
            'email_to': 'someone@example.org',
            'subject': 'Hi',
            'body_html': '<p>Hello</p>',
            **values,
        })

    # ------------------------------------------------------------------
    def test_reply_prefills_sender_and_subject(self):
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='reply', message_id=self.parent.id,
        )
        self.assertEqual(payload['email_to'], '"Budi" <budi@customer.co.id>')
        self.assertEqual(payload['subject'], 'Re: Quotation request')

    def test_reply_does_not_double_the_re_prefix(self):
        self.parent.subject = 'Re: Quotation request'
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='reply', message_id=self.parent.id,
        )
        self.assertEqual(payload['subject'], 'Re: Quotation request')

    def test_reply_all_excludes_our_own_address(self):
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='reply_all', message_id=self.parent.id,
        )
        self.assertNotIn(
            'me@example.org', payload['email_cc'],
            "Replying to all must not send us a copy of our own mail.",
        )
        self.assertIn('boss@customer.co.id', payload['email_cc'])

    def test_forward_uses_fwd_prefix_and_no_recipient(self):
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='forward', message_id=self.parent.id,
        )
        self.assertEqual(payload['subject'], 'Fwd: Quotation request')
        self.assertEqual(payload['email_to'], '')

    def test_reply_quotes_the_original_body(self):
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='reply', message_id=self.parent.id,
        )
        self.assertIn('blockquote', payload['body_html'])
        self.assertIn('Please send a quotation.', payload['body_html'])

    # ------------------------------------------------------------------
    def test_threading_headers_chain_the_conversation(self):
        draft = self._draft(parent_id=self.parent.id, compose_mode='reply')
        references, headers = draft._threading_headers()
        self.assertEqual(headers['In-Reply-To'], '<original@customer.co.id>')
        self.assertEqual(references, '<older@customer.co.id> <original@customer.co.id>')

    def test_new_message_has_no_threading_headers(self):
        references, headers = self._draft()._threading_headers()
        self.assertEqual(references, '')
        self.assertEqual(headers, {})

    def test_sending_requires_a_recipient(self):
        draft = self._draft(email_to='')
        with self.assertRaises(UserError):
            draft.action_send()

    def test_sending_requires_an_outgoing_server(self):
        self.server.smtp_server_id = False
        draft = self._draft()
        with self.assertRaises(UserError):
            draft.action_send()

    # ------------------------------------------------------------------
    # outgoing server selection
    # ------------------------------------------------------------------
    def test_shared_server_is_the_fallback(self):
        self.assertEqual(self.account._resolve_mail_server(), self.mail_server)
        self.assertIn('fallback', self.account.smtp_source)

    def test_smtp_source_warns_when_the_server_cannot_send_as_us(self):
        """Surface the rejection in the form, not only at send time."""
        self.mail_server.from_filter = 'someone.else@example.org'
        self.account.invalidate_recordset(['smtp_source'])
        self.assertIn('WILL BE REJECTED', self.account.smtp_source)
        self.assertIn('me@example.org', self.account.smtp_source)

    def test_personal_server_wins_over_the_shared_one(self):
        """A per-user server is what makes multi-user sending work at all."""
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Sales', 'login': 'mc_sales', 'email': 'sales@example.org',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        personal = self.env['ir.mail_server'].create({
            'name': 'sales personal',
            'smtp_host': 'mail.example.org',
            'smtp_port': 587,
            'from_filter': 'sales@example.org',
            'owner_user_id': user.id,
        })
        account = self.env['mail.client.account'].create({
            'name': 'Sales', 'email': 'sales@example.org',
            'server_id': self.server.id, 'user_id': user.id,
        })
        self.assertEqual(account._resolve_mail_server(), personal)
        self.assertIn('personal', account.smtp_source)

    def test_explicit_override_wins_over_everything(self):
        other = self.env['ir.mail_server'].create({
            'name': 'explicit', 'smtp_host': 'mail.example.org', 'smtp_port': 587,
        })
        self.account.smtp_server_id = other
        self.assertEqual(self.account._resolve_mail_server(), other)

    def test_personal_servers_are_excluded_from_odoo_notifications(self):
        """Core behaviour this design leans on - worth pinning down."""
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Solo', 'login': 'mc_solo', 'email': 'solo@example.org',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        personal = self.env['ir.mail_server'].create({
            'name': 'solo personal', 'smtp_host': 'mail.example.org',
            'smtp_port': 587, 'from_filter': 'solo@example.org',
            'owner_user_id': user.id,
        })
        pool = self.env['ir.mail_server'].search(
            self.env['ir.mail_server']._find_mail_server_allowed_domain()
        )
        self.assertNotIn(
            personal, pool,
            "A user's own SMTP credential must never be picked up for "
            "unrelated Odoo notifications.",
        )

    def test_mismatched_sender_is_refused_before_smtp(self):
        """Fail with the address that is wrong, not with a cryptic 5.7.1."""
        self.mail_server.from_filter = 'someone.else@example.org'
        draft = self._draft()
        with self.assertRaises(UserError) as caught:
            draft.action_send()
        self.assertIn('me@example.org', str(caught.exception))

    def test_domain_from_filter_is_accepted(self):
        self.mail_server.from_filter = 'example.org'
        self.account._check_sender_allowed(self.mail_server)

    def test_empty_from_filter_allows_anything(self):
        self.mail_server.from_filter = False
        self.account._check_sender_allowed(self.mail_server)

    def test_personal_server_with_mismatched_owner_email_is_explained(self):
        """The exact trap core reports as "the owner does not use it anymore"."""
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin', 'login': 'mc_admin_mismatch', 'email': 'admin@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        personal = self.env['ir.mail_server'].create({
            'name': 'Mailcow personal', 'smtp_host': 'mail.example.org', 'smtp_port': 587,
            'from_filter': 'real.name@example.org',
            'smtp_user': 'real.name@example.org',
            'owner_user_id': user.id,
        })
        with self.assertRaises(UserError) as caught:
            self.account._check_sender_allowed(personal)
        message = str(caught.exception)
        self.assertIn('admin@example.com', message)
        self.assertIn('FROM Filtering', message)

    def test_personal_server_wiring_accepts_a_consistent_setup(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Consistent', 'login': 'mc_consistent', 'email': 'ok@example.org',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        personal = self.env['ir.mail_server'].create({
            'name': 'ok personal', 'smtp_host': 'mail.example.org', 'smtp_port': 587,
            'from_filter': 'ok@example.org',
            'smtp_user': 'ok@example.org',
            'owner_user_id': user.id,
        })
        self.env['mail.client.account']._check_personal_server_wiring(personal)
        self.assertEqual(
            user.outgoing_mail_server_id, personal,
            "Core must now recognise the server as this user's own.",
        )

    def test_personal_server_without_from_filter_is_reported_clearly(self):
        """Core refuses this case with a message that names no remedy."""
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'NoFilter', 'login': 'mc_nofilter', 'email': 'nf@example.org',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        personal = self.env['ir.mail_server'].create({
            'name': 'nf personal', 'smtp_host': 'mail.example.org',
            'smtp_port': 587, 'owner_user_id': user.id,
        })
        with self.assertRaises(UserError) as caught:
            self.account._check_sender_allowed(personal)
        self.assertIn('FROM Filtering', str(caught.exception))

    def test_send_builds_and_files_a_copy(self):
        draft = self._draft(parent_id=self.parent.id, compose_mode='reply')
        sent_messages = []

        def fake_send(self_ims, message, **kwargs):
            sent_messages.append(message)
            return message['Message-Id']

        with patch.object(type(self.env['ir.mail_server']), 'send_email', fake_send), \
             patch.object(type(draft), '_append_to_sent', lambda self, msg: True):
            draft.action_send()

        self.assertEqual(draft.state, 'sent')
        self.assertEqual(len(sent_messages), 1)
        message = sent_messages[0]
        self.assertEqual(message['In-Reply-To'], '<original@customer.co.id>')
        self.assertIn('<original@customer.co.id>', message['References'])
        self.assertEqual(message['From'], 'me@example.org')

    def test_replying_marks_the_original_answered(self):
        draft = self._draft(parent_id=self.parent.id, compose_mode='reply')
        with patch.object(type(self.env['ir.mail_server']), 'send_email',
                          lambda *a, **k: 'ok'), \
             patch.object(type(draft), '_append_to_sent', lambda self, msg: True):
            draft.action_send()
        self.assertTrue(
            self.parent.flag_answered,
            "The original should show as answered, as in any mail client.",
        )

    def test_a_failed_append_does_not_look_like_a_failed_send(self):
        draft = self._draft()
        with patch.object(type(self.env['ir.mail_server']), 'send_email',
                          lambda *a, **k: 'ok'), \
             patch.object(type(self.account), '_open_connection',
                          side_effect=UserError("no connection")):
            draft.action_send()
        self.assertEqual(
            draft.state, 'sent',
            "The mail was delivered; only filing the copy failed.",
        )

    # ------------------------------------------------------------------
    def test_empty_drafts_are_collected(self):
        """Opening the composer and walking away must not litter the list."""
        empty = self._draft(email_to='', subject='', body_html='<p><br></p>')
        typed = self._draft(subject='Real one')
        old = fields.Datetime.now() - timedelta(days=2)
        self.env.cr.execute(
            "UPDATE mail_client_compose SET write_date = %s WHERE id IN %s",
            (old, tuple([empty.id, typed.id])),
        )
        (empty | typed).invalidate_recordset(['write_date'])

        self.env['mail.client.compose']._cron_gc_empty_drafts()
        self.assertFalse(empty.exists())
        self.assertTrue(typed.exists(), "A draft with a subject must be kept.")

    def test_recent_empty_drafts_are_left_alone(self):
        """Someone may still be typing in another tab."""
        empty = self._draft(email_to='', subject='', body_html='')
        self.env['mail.client.compose']._cron_gc_empty_drafts()
        self.assertTrue(empty.exists())

    def test_recipient_search_only_returns_contacts_with_an_email(self):
        self.env['res.partner'].create([
            {'name': 'Sagara Teknik', 'email': 'info@sagara.co.id'},
            {'name': 'Sagara No Email'},
        ])
        results = self.env['mail.client.compose'].search_recipients('Sagara')
        names = {row['name'] for row in results}
        self.assertIn('Sagara Teknik', names)
        self.assertNotIn(
            'Sagara No Email', names,
            "Suggesting a contact you cannot send to is worse than no suggestion.",
        )
        self.assertEqual(results[0]['value'], '"Sagara Teknik" <info@sagara.co.id>')

    def test_recipient_search_ignores_very_short_terms(self):
        self.assertEqual(self.env['mail.client.compose'].search_recipients('a'), [])

    # ------------------------------------------------------------------
    # what reaches the editor
    # ------------------------------------------------------------------
    def test_reply_payload_carries_the_quoted_original(self):
        payload = self.env['mail.client.compose'].start(
            self.account.id, mode='reply', message_id=self.parent.id)
        self.assertIn('blockquote', payload['body_html'])
        self.assertIn('Please send a quotation.', payload['body_html'])

    def test_payload_body_is_sanitised(self):
        """The composer writes this into a contenteditable, not an iframe."""
        draft = self._draft(body_html='<p>Hi</p><img src="x" onerror="alert(1)">')
        payload = draft._to_payload()
        self.assertNotIn('onerror', payload['body_html'])
        self.assertIn('Hi', payload['body_html'])

    def test_payload_body_keeps_ordinary_email_html(self):
        """Sanitising must not eat the formatting people actually send."""
        draft = self._draft(body_html=(
            '<p style="color:#333">Dear Budi,</p>'
            '<table><tr><td>Item</td></tr></table>'
            '<a href="https://example.org">link</a>'
        ))
        body = draft._to_payload()['body_html']
        for fragment in ('color:#333', '<table', '<td', 'https://example.org'):
            self.assertIn(fragment, body)

    def test_drafts_are_private_to_their_author(self):
        other = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other', 'login': 'mc_other', 'email': 'other@example.org',
            'group_ids': [(6, 0, [
                self.env.ref('mail_client.group_mail_client_user').id,
                self.env.ref('base.group_user').id,
            ])],
        })
        draft = self._draft()
        self.assertNotIn(
            draft, self.env['mail.client.compose'].with_user(other).search([]),
            "A half-written message must never be visible to anyone else.",
        )
