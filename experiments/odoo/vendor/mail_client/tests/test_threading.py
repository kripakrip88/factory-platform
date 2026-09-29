# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Conversation grouping, signatures, contact context and the unified inbox."""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


class _BodyConnection:
    """ПРАВКА ПМК (шаг 20): ящик, который отдаёт тело письма целиком."""

    def __init__(self, html, text):
        self.html, self.text = html, text
        self.selected = []
        self.closed = False

    def select(self, path, readonly=True, **_kwargs):
        self.selected.append((path, readonly))
        return {}

    def fetch_structure(self, uid):
        return []

    def fetch_body(self, uid):
        return self.html, self.text, False

    def close(self):
        self.closed = True


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

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 20): переписка целиком под письмом
    # ------------------------------------------------------------------
    def test_thread_rows_carry_what_the_conversation_shows(self):
        sent = self._folder('Sent', role='sent')
        first = self._message(1, 'Question', '<root@x>', 1, sender='Client <client@firm.ru>')
        ours = self._message(2, 'Re: Question', '<root@x>', 2, folder=sent,
                             sender='Me <me@example.org>')
        ours.write({'email_to': 'Client <client@firm.ru>', 'body_state': 'fetched',
                    'structure_state': 'parsed', 'body_html': '<p>Ответ</p>'})
        # Своя копия во «Входящих» — «мы» по адресу ящика, регистр не важен.
        copy = self._message(3, 'Re: Question', '<root@x>', 3, sender='"Me" <ME@Example.org>')

        thread = self.Message.get_thread(first.id)
        self.assertEqual([row['id'] for row in thread], [first.id, ours.id, copy.id])
        rows = {row['id']: row for row in thread}
        self.assertFalse(rows[first.id]['is_outgoing'])
        self.assertTrue(rows[ours.id]['is_outgoing'])
        self.assertTrue(rows[copy.id]['is_outgoing'])
        self.assertEqual(rows[first.id]['folder_role'], 'inbox')
        self.assertEqual(rows[ours.id]['folder_role'], 'sent')
        self.assertEqual(rows[ours.id]['email_to'], 'Client <client@firm.ru>')
        self.assertEqual(rows[ours.id]['body_state'], 'fetched')
        self.assertEqual(rows[first.id]['body_state'], 'header_only')

    def test_thread_keeps_the_copy_that_was_opened(self):
        """Окно ищет открытое письмо в переписке по id — из двух копий
        остаётся та, которую открыли."""
        sent = self._folder('Sent', role='sent')
        self._message(1, 'Question', '<root@x>', 1)
        in_sent = self._message(2, 'Re', '<root@x>', 2, folder=sent, message_id='<dup@x>')
        in_inbox = self._message(3, 'Re', '<root@x>', 2, message_id='<dup@x>')
        for opened, other in ((in_inbox, in_sent), (in_sent, in_inbox)):
            ids = [row['id'] for row in self.Message.get_thread(opened.id)]
            self.assertEqual(len(ids), 2, "Копии — одно письмо.")
            self.assertIn(opened.id, ids)
            self.assertNotIn(other.id, ids)

    def test_detail_carries_the_preview(self):
        message = self._message(1, 'Question', '<root@x>', 1)
        message.write({'body_state': 'fetched', 'structure_state': 'parsed',
                       'body_html': '<p>Текст</p>', 'preview': 'Начало текста'})
        self.assertEqual(self.Message.get_message_detail(message.id)['preview'], 'Начало текста')

    def test_failed_body_is_fetched_again(self):
        """Один сбой связи больше не оставляет письмо «не удалось загрузить»
        навсегда. Чтение — только на просмотр (EXAMINE)."""
        message = self._message(1, 'Question', '<root@x>', 1)
        message.write({'body_state': 'failed', 'structure_state': 'failed'})
        connection = _BodyConnection('<p>Счёт во вложении</p>', 'Счёт во вложении')
        with patch.object(type(self.account), '_open_connection',
                          return_value=connection) as opener:
            detail = self.Message.get_message_detail(message.id)
        opener.assert_called_once()
        self.assertEqual(connection.selected, [('INBOX', True)])
        self.assertTrue(connection.closed)
        self.assertEqual(message.body_state, 'fetched')
        self.assertIn('Счёт во вложении', detail['body'])
        self.assertEqual(detail['body_state'], 'fetched')
        self.assertEqual(detail['preview'], 'Счёт во вложении')
        with patch.object(type(self.account), '_open_connection') as opener:
            self.Message.get_message_detail(message.id)
        opener.assert_not_called()

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
        # ПРАВКА ПМК (шаг 18): ящики — свои. Без владельца «Все входящие» были
        # зелёными только из-за ошибки: пустой список ящиков читался как «все
        # письма базы», а в базе теста других писем нет.
        (self.account | second).user_id = self.env.uid
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
        self.account.user_id = self.env.uid  # ПРАВКА ПМК (шаг 18), см. выше
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

    def test_unified_inbox_without_a_mailbox_lists_nothing(self):
        """ПРАВКА ПМК (шаг 18): нет своего ящика — пустой список.

        Раньше пустой набор ящиков снимал условие на папку, и «Все входящие»
        отдавали каждое письмо базы — Отправленные, Спам, чужие ящики.
        """
        sent = self._folder('Sent', role='sent')
        self._message(1, 'In inbox', '<a@x>', 1)
        self._message(2, 'In sent', '<b@x>', 2, folder=sent)
        self.assertFalse(self.account.user_id, "Ящик ничей — у пользователя ящиков нет.")
        Folder = self.env['mail.client.folder']
        for threaded in (False, True):
            result = Folder.get_messages(unified=True, threaded=threaded)
            self.assertEqual(result['messages'], [], "threaded=%s" % threaded)
            self.assertFalse(result['has_more'])
        self.assertFalse(Folder.get_messages(unified=True, message_filter='unread')['messages'])

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 18, Б1): «Загрузить ещё» в режиме переписок
    # ------------------------------------------------------------------
    def test_load_more_does_not_repeat_a_conversation(self):
        """Переписка с первой страницы не возвращается своим старым письмом."""
        self._message(1, 'A old', '<a@x>', 1)
        self._message(2, 'A new', '<a@x>', 5)
        self._message(3, 'B', '<b@x>', 3)
        Folder = self.env['mail.client.folder']
        keys, before = [], None
        for _page in range(4):
            result = Folder.get_messages(
                folder_id=self.inbox.id, threaded=True, limit=1, before=before)
            if not result['messages']:
                break
            keys += [row['thread_key'] for row in result['messages']]
            before = result['messages'][-1]['date']
        self.assertEqual(keys, ['<a@x>', '<b@x>'])

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 18): строка нашего письма — «Кому: …»
    # ------------------------------------------------------------------
    def test_row_marks_outgoing_and_recipient(self):
        sent = self._folder('Sent', role='sent')
        ours = self.Message.create({
            'account_id': self.account.id, 'folder_id': sent.id, 'imap_uid': 1,
            'subject': 'Offer', 'thread_key': '<o@x>', 'email_from': 'Me <me@example.org>',
            'email_to': 'Client <client@firm.ru>, boss@firm.ru',
            'date': datetime(2026, 8, 3, 10, 0, 0),
        })
        # Своя копия во «Входящих»: признак — адрес ящика (регистр не важен).
        copy = self._message(2, 'Copy to self', '<c@x>', 2, sender='"Me" <ME@Example.org>')
        theirs = self._message(3, 'Question', '<q@x>', 1, sender='client@firm.ru')

        rows = {row['id']: row for row in sent.get_messages(folder_id=sent.id)['messages']}
        self.assertTrue(rows[ours.id]['is_outgoing'])
        self.assertEqual(rows[ours.id]['email_to'], 'Client <client@firm.ru>, boss@firm.ru')

        inbox_rows = {row['id']: row for row in self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)['messages']}
        self.assertTrue(inbox_rows[copy.id]['is_outgoing'])
        self.assertFalse(inbox_rows[theirs.id]['is_outgoing'])
        self.assertIn('email_to', inbox_rows[theirs.id])

        long_to = ', '.join('user%s@firm.ru' % i for i in range(100))
        ours.email_to = long_to
        payload = ours._to_list_payload()[0]
        self.assertEqual(payload['email_to'], long_to[:512], "В строку — не больше 512 знаков.")

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 18, Г10): «ждёт ответа» / «ждём клиента»
    # ------------------------------------------------------------------
    def _recent(self, uid, key, days_ago, folder=None, sender='client@firm.ru', **extra):
        values = {
            'account_id': self.account.id, 'folder_id': (folder or self.inbox).id,
            'imap_uid': uid, 'subject': key, 'thread_key': key, 'email_from': sender,
            'message_id': '<m%s@x>' % uid,
            'date': fields.Datetime.now() - timedelta(days=days_ago, hours=1),
        }
        values.update(extra)
        return self.Message.create(values)

    def test_row_reports_who_waits(self):
        sent = self._folder('Sent', role='sent')
        drafts = self._folder('Drafts', role='drafts')
        spam = self._folder('Spam', role='spam')
        trash = self._folder('Trash', role='trash')
        me = 'me@example.org'
        # Последнее — от клиента: ждёт нашего ответа.
        self._recent(1, '<us@x>', 1)
        # Клиент, потом наш ответ: ждём клиента.
        self._recent(2, '<client@x>', 3)
        self._recent(3, '<client@x>', 2, folder=sent, sender=me)
        # Наш черновик после письма клиента ответом не считается.
        self._recent(4, '<draft@x>', 2)
        self._recent(5, '<draft@x>', 1, folder=drafts, sender=me)
        self._recent(6, '<draft@x>', 1, sender=me, flag_draft=True)
        # Письмо клиента в Спаме или Корзине переписку не решает: последним
        # остаётся наш ответ.
        self._recent(7, '<spam@x>', 3)
        self._recent(8, '<spam@x>', 2, folder=sent, sender=me)
        self._recent(9, '<spam@x>', 1, folder=spam)
        self._recent(10, '<spam@x>', 1, folder=trash)
        # Старше окна — плашки нет; робот ответа не ждёт.
        self._recent(11, '<old@x>', 10)
        self._recent(12, '<robot@x>', 1, sender='Shop <no-reply@shop.ru>')
        self._recent(13, '<daemon@x>', 1, sender='MAILER-DAEMON@mail.ru')

        rows = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)['messages']
        awaiting = {row['thread_key']: row['awaiting'] for row in rows}
        self.assertEqual(awaiting, {
            '<us@x>': 'us', '<client@x>': 'client', '<draft@x>': 'us',
            '<spam@x>': 'client', '<old@x>': False, '<robot@x>': False, '<daemon@x>': False,
        })

        # Строка из тихой папки плашки не несёт.
        spam_rows = self.env['mail.client.folder'].get_messages(
            folder_id=spam.id, threaded=True)['messages']
        self.assertEqual([row['awaiting'] for row in spam_rows], [False])

        # Без переписок плашек нет вовсе.
        flat = self.env['mail.client.folder'].get_messages(folder_id=self.inbox.id)['messages']
        self.assertTrue(all('awaiting' not in row for row in flat))

    def test_spam_copy_does_not_hide_the_message(self):
        """Копия письма в Спаме и во «Входящих» — одно письмо: оставшейся
        копией не должна стать спамная, иначе письмо выпадет из расчёта."""
        spam = self._folder('Spam', role='spam')
        self._recent(1, '<k@x>', 1, message_id='<same@x>')
        self._recent(2, '<k@x>', 1, folder=spam, message_id='<same@x>')
        rows = self.env['mail.client.folder'].get_messages(
            folder_id=self.inbox.id, threaded=True)['messages']
        self.assertEqual(rows[0]['awaiting'], 'us')

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
