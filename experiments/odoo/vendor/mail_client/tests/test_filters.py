# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Quick filters on the message list."""
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMessageFilters(TransactionCase):

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
        cls.partner = cls.env['res.partner'].create({
            'name': 'Budi Santoso', 'email': 'budi@example.co.id',
        })
        cls.Folder = cls.env['mail.client.folder']
        cls.Message = cls.env['mail.client.message']

    def _message(self, uid, subject, day=1, seen=True, flagged=False,
                 sender='stranger@example.com', thread_key=None, folder=None,
                 attachment=False):
        folder = folder or self.inbox
        return self.Message.create({
            'account_id': folder.account_id.id,
            'folder_id': folder.id,
            'imap_uid': uid,
            'subject': subject,
            'email_from': sender,
            'flag_seen': seen,
            'flag_flagged': flagged,
            'has_attachment': attachment,
            'structure_state': 'parsed' if attachment else 'unknown',
            'thread_key': thread_key or '<%s@x>' % uid,
            'date': datetime(2026, 8, day, 10, 0, 0),
        })

    def _subjects(self, **kwargs):
        result = self.Folder.get_messages(folder_id=self.inbox.id, **kwargs)
        return sorted(row['subject'] for row in result['messages'])

    # ------------------------------------------------------------------
    # flat list
    # ------------------------------------------------------------------
    def test_no_filter_lists_everything(self):
        self._message(1, 'Read', seen=True)
        self._message(2, 'Unread', seen=False)
        self.assertEqual(self._subjects(), ['Read', 'Unread'])
        self.assertEqual(self._subjects(message_filter='all'), ['Read', 'Unread'])

    def test_unread_filter(self):
        self._message(1, 'Read', seen=True)
        self._message(2, 'Unread', seen=False)
        self.assertEqual(self._subjects(message_filter='unread'), ['Unread'])

    def test_read_filter(self):
        self._message(1, 'Read', seen=True)
        self._message(2, 'Unread', seen=False)
        self.assertEqual(self._subjects(message_filter='read'), ['Read'])

    def test_starred_filter(self):
        self._message(1, 'Plain')
        self._message(2, 'Starred', flagged=True)
        self.assertEqual(self._subjects(message_filter='flagged'), ['Starred'])

    def test_attachments_filter(self):
        self._message(1, 'Plain')
        self._message(2, 'With an invoice', attachment=True)
        self.assertEqual(self._subjects(message_filter='attachments'),
                         ['With an invoice'])

    def test_contact_filter_uses_the_resolved_partner(self):
        """The link is made when the message is stored, not when it is read.

        That is what makes this filter usable on a header-only mailbox: no
        message has to have been opened for it to answer correctly.
        """
        known = self._message(1, 'From a customer', sender='Budi <budi@example.co.id>')
        self._message(2, 'From a stranger')
        self.assertEqual(known.partner_id, self.partner)
        self.assertEqual(self._subjects(message_filter='contact'), ['From a customer'])

    def test_filter_narrows_the_search_results(self):
        self._message(1, 'Quotation', seen=False)
        self._message(2, 'Quotation follow-up', seen=True)
        self._message(3, 'Invoice', seen=False)
        self.assertEqual(
            self._subjects(search='Quotation', message_filter='unread'), ['Quotation'])

    def test_filter_survives_paging(self):
        """Page two must be filtered like page one, or it reintroduces the rest."""
        for day in range(1, 6):
            self._message(day, 'Unread %s' % day, day=day, seen=False)
            self._message(day + 100, 'Read %s' % day, day=day, seen=True)

        first = self.Folder.get_messages(
            folder_id=self.inbox.id, limit=2, message_filter='unread')
        self.assertTrue(first['has_more'])
        oldest = first['messages'][-1]['date']

        second = self.Folder.get_messages(
            folder_id=self.inbox.id, limit=2, before=oldest, message_filter='unread')
        self.assertTrue(all(not row['flag_seen'] for row in second['messages']))

    def test_unknown_filter_is_refused(self):
        """Silently ignoring it would show an unfiltered list under a filter."""
        self._message(1, 'Anything')
        with self.assertRaises(UserError):
            self.Folder.get_messages(folder_id=self.inbox.id, message_filter='starred')

    def test_filter_is_reported_back(self):
        self._message(1, 'Anything')
        result = self.Folder.get_messages(folder_id=self.inbox.id, message_filter='unread')
        self.assertEqual(result['filter'], 'unread')
        self.assertEqual(
            self.Folder.get_messages(folder_id=self.inbox.id)['filter'], 'all')

    # ------------------------------------------------------------------
    # filters and conversations together
    # ------------------------------------------------------------------
    def test_unread_filter_lists_the_conversation_once(self):
        self._message(1, 'Quotation', day=1, seen=True, thread_key='<root@x>')
        self._message(2, 'Re: Quotation', day=2, seen=False, thread_key='<root@x>')

        result = self.Folder.get_messages(
            folder_id=self.inbox.id, threaded=True, message_filter='unread')
        self.assertEqual(len(result['messages']), 1)
        row = result['messages'][0]
        # The row is the message that matched, so opening it lands on the mail
        # that is actually unread rather than on a reply already read.
        self.assertEqual(row['subject'], 'Re: Quotation')
        # The badge still describes the whole conversation: the filter chooses
        # which conversations to show, not how big they are.
        self.assertEqual(row['thread_count'], 2)
        self.assertEqual(row['unread_count'], 1)

    def test_conversation_without_a_match_is_hidden(self):
        self._message(1, 'All read', day=1, seen=True, thread_key='<read@x>')
        self._message(2, 'Re: All read', day=2, seen=True, thread_key='<read@x>')
        self._message(3, 'Has something new', day=3, seen=False, thread_key='<new@x>')

        result = self.Folder.get_messages(
            folder_id=self.inbox.id, threaded=True, message_filter='unread')
        self.assertEqual([row['subject'] for row in result['messages']],
                         ['Has something new'])

    def test_read_filter_keeps_the_conversation_marked_unread(self):
        """A conversation is unread while any of its messages is.

        Filtering on read picks the conversation through its read message, but
        the row still stands for the exchange, so it stays bold. Reporting it
        as read here would contradict the same row seen without the filter.
        """
        self._message(1, 'Opened', day=1, seen=True, thread_key='<root@x>')
        self._message(2, 'Re: Opened', day=2, seen=False, thread_key='<root@x>')

        result = self.Folder.get_messages(
            folder_id=self.inbox.id, threaded=True, message_filter='read')
        row = result['messages'][0]
        self.assertEqual(row['subject'], 'Opened')
        self.assertFalse(row['flag_seen'])

    # ------------------------------------------------------------------
    # unified inbox
    # ------------------------------------------------------------------
    def test_filter_applies_to_the_unified_inbox(self):
        other_account = self.env['mail.client.account'].create({
            'name': 'Second', 'email': 'other@example.org', 'server_id': self.server.id,
        })
        # ПРАВКА ПМК (шаг 18): ящики — свои. Без владельца тест был зелёным
        # только из-за ошибки «пустой список ящиков = все письма базы».
        (self.account | other_account).user_id = self.env.uid
        other_inbox = self.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': other_account.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })
        self._message(1, 'Unread here', seen=False)
        self._message(2, 'Read here', seen=True)
        self._message(3, 'Unread there', seen=False, folder=other_inbox)

        result = self.Folder.get_messages(unified=True, message_filter='unread')
        self.assertEqual(sorted(row['subject'] for row in result['messages']),
                         ['Unread here', 'Unread there'])

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 18, Г11): поиск по получателю
    # ------------------------------------------------------------------
    def test_search_finds_the_recipient(self):
        """В «Отправленных» «От» везде наш ящик — письмо клиенту ищут по его
        адресу в «Кому» или «Копии»."""
        sent = self.Folder.create({
            'name': 'Sent', 'account_id': self.account.id, 'imap_path': 'Sent', 'role': 'sent',
        })
        self._message(1, 'Offer', folder=sent, sender='me@example.org')
        self._message(2, 'Invoice', folder=sent, sender='me@example.org')
        self._message(3, 'Other', folder=sent, sender='me@example.org')
        self.Message.search([('subject', '=', 'Offer')]).email_to = 'Client <client@firm.ru>'
        self.Message.search([('subject', '=', 'Invoice')]).write({
            'email_to': 'accounts@firm.ru', 'email_cc': 'client@firm.ru'})
        for threaded in (False, True):
            result = self.Folder.get_messages(
                folder_id=sent.id, search='client@firm.ru', threaded=threaded)
            self.assertEqual(sorted(row['subject'] for row in result['messages']),
                             ['Invoice', 'Offer'], "threaded=%s" % threaded)

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 18, Г10): фильтр «Ждут ответа»
    # ------------------------------------------------------------------
    def _recent(self, uid, key, days_ago, folder=None, sender='client@firm.ru'):
        folder = folder or self.inbox
        return self.Message.create({
            'account_id': folder.account_id.id, 'folder_id': folder.id, 'imap_uid': uid,
            'subject': key, 'thread_key': key, 'email_from': sender,
            'message_id': '<m%s-%s@x>' % (folder.id, uid),
            'date': fields.Datetime.now() - timedelta(days=days_ago, hours=1),
        })

    def test_awaiting_filter(self):
        sent = self.Folder.create({
            'name': 'Sent', 'account_id': self.account.id, 'imap_path': 'Sent', 'role': 'sent',
        })
        self._recent(1, '<us@x>', 2)
        self._recent(2, '<us@x>', 1)                                  # два письма клиента
        self._recent(3, '<client@x>', 3)
        self._recent(1, '<client@x>', 2, folder=sent, sender='me@example.org')
        self._recent(4, '<old@x>', 10)
        self._recent(5, '<robot@x>', 1, sender='noreply@shop.ru')
        self.assertEqual(self._subjects(message_filter='awaiting'), ['<us@x>', '<us@x>'],
                         "Без переписок — все письма таких переписок в папке.")

        result = self.Folder.get_messages(
            folder_id=self.inbox.id, threaded=True, message_filter='awaiting')
        self.assertEqual([row['thread_key'] for row in result['messages']], ['<us@x>'])
        self.assertEqual(result['filter'], 'awaiting')

        # Фильтр совпадает с плашкой строки: всё, что «ждёт ответа» в списке,
        # есть в фильтре, и ничего больше.
        rows = self.Folder.get_messages(folder_id=self.inbox.id, threaded=True)['messages']
        self.assertEqual({row['thread_key'] for row in rows if row['awaiting'] == 'us'},
                         {row['thread_key'] for row in result['messages']})

        # В «Отправленных» переписка клиента видна своим нашим письмом.
        in_sent = self.Folder.get_messages(folder_id=sent.id, message_filter='awaiting')
        self.assertEqual(in_sent['messages'], [])

    def test_awaiting_filter_in_the_unified_inbox(self):
        other_account = self.env['mail.client.account'].create({
            'name': 'Second', 'email': 'other@example.org', 'server_id': self.server.id,
        })
        other_inbox = self.Folder.create({
            'name': 'INBOX', 'account_id': other_account.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })
        self._recent(1, '<here@x>', 1)
        self._recent(1, '<there@x>', 1, folder=other_inbox)
        self._recent(2, '<answered@x>', 1, folder=other_inbox, sender='other@example.org')
        self.assertEqual(self.Folder.get_messages(unified=True, message_filter='awaiting')['messages'],
                         [], "Чужие ящики — не мои: фильтр по ним не ищет.")

        (self.account | other_account).user_id = self.env.uid
        for threaded in (False, True):
            result = self.Folder.get_messages(
                unified=True, threaded=threaded, message_filter='awaiting')
            self.assertEqual(sorted(row['subject'] for row in result['messages']),
                             ['<here@x>', '<there@x>'], "threaded=%s" % threaded)

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 18): тихие папки
    # ------------------------------------------------------------------
    def test_inbox_state_marks_spam_and_trash_quiet(self):
        self.account.user_id = self.env.uid
        for name, role in (('Junk', 'spam'), ('Trash', 'trash'), ('Sent', 'sent'),
                           ('Projects', 'other')):
            self.Folder.create({
                'name': name, 'account_id': self.account.id, 'imap_path': name, 'role': role,
            })
        state = self.env['mail.client.account'].get_inbox_state()
        account = next(a for a in state['accounts'] if a['id'] == self.account.id)
        quiet = {folder['name']: folder['quiet'] for folder in account['folders']}
        self.assertEqual(quiet, {
            'INBOX': False, 'Sent': False, 'Junk': True, 'Trash': True, 'Projects': False,
        })
