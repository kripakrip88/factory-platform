# -*- coding: utf-8 -*-
"""ПРАВКА ПМК (шаг 41 разбора удобства, 05.10.2026): список писем.

- Поиск «по всем папкам», кроме Спама и Корзины (А7): ``search_everywhere``
  у get_messages, без переписок и в режиме переписок, в «Все входящие» —
  только доступные ящики; в самих Спаме и Корзине — только в них; копии
  одного письма в двух папках — одна строка (копия во «Входящих»), и на
  границе страниц тоже.
- «Загрузить ещё» без пропусков и повторов на равных датах (Б1): второй
  ключ страницы ``before_id`` — id строки, у переписок ``thread_max_id``.
  Старый вызов без него работает как раньше.
- ``total`` у папки в get_inbox_state (А8: пустые папки — под «Ещё папки»),
  ``folder_id`` у строки (метка папки в результатах поиска).
- Крючок ``_decorate_thread_rows`` получает строки и письма переписок.

Гонять на одноразовой базе:
    odoo -d mc_test -i mail_client --test-enable \
         --test-tags /mail_client:TestStep41List --stop-after-init
"""
from datetime import datetime
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStep41List(TransactionCase):

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
        cls.account.user_id = cls.env.uid
        Folder = cls.env['mail.client.folder']

        def folder(name, role, account=None):
            return Folder.create({
                'name': name, 'account_id': (account or cls.account).id,
                'imap_path': name, 'role': role,
            })

        cls.inbox = folder('INBOX', 'inbox')
        cls.sent = folder('Sent', 'sent')
        cls.drawings = folder('Drawings', 'other')
        cls.spam = folder('Junk', 'spam')
        cls.trash = folder('Trash', 'trash')
        cls.Folder = Folder
        cls.Message = cls.env['mail.client.message']
        cls.uid_seq = 0

    def _message(self, folder, subject, day=1, hour=10, key=None, message_id=None,
                 account=None, seen=True):
        type(self).uid_seq += 1
        uid = self.uid_seq
        return self.Message.create({
            'account_id': (account or self.account).id,
            'folder_id': folder.id,
            'imap_uid': uid,
            'subject': subject,
            'thread_key': key or '<t%s@x>' % uid,
            'message_id': message_id or '<m%s@x>' % uid,
            'email_from': 'client@firm.ru',
            'flag_seen': seen,
            'date': datetime(2026, 9, day, hour, 0, 0),
        })

    # ------------------------------------------------------------------
    # А7: поиск по всем папкам, кроме Спама и Корзины
    # ------------------------------------------------------------------
    def test_search_everywhere_skips_spam_and_trash(self):
        self._message(self.inbox, 'Счёт 00627 входящий', day=5)
        self._message(self.sent, 'Re: Счёт 00627', day=6)
        self._message(self.drawings, 'Счёт 00627 чертёж', day=4)
        self._message(self.spam, 'Счёт 00627 спам', day=7)
        self._message(self.trash, 'Счёт 00627 удалён', day=8)
        for threaded in (False, True):
            result = self.Folder.get_messages(
                folder_id=self.inbox.id, search='00627', search_everywhere=True,
                threaded=threaded)
            folders = {row['folder_id'] for row in result['messages']}
            self.assertEqual(folders, {self.inbox.id, self.sent.id, self.drawings.id},
                             'threaded=%s' % threaded)
            self.assertEqual(result['scope'], 'everywhere')

    def test_without_the_flag_search_stays_in_the_folder(self):
        self._message(self.inbox, 'Счёт 00627', day=5)
        self._message(self.sent, 'Re: Счёт 00627', day=6)
        result = self.Folder.get_messages(folder_id=self.inbox.id, search='00627')
        self.assertEqual([row['folder_id'] for row in result['messages']], [self.inbox.id])
        self.assertEqual(result['scope'], 'folder')

    def test_inside_spam_search_is_only_spam(self):
        self._message(self.inbox, 'Счёт 00627', day=5)
        self._message(self.spam, 'Счёт 00627 спам', day=7)
        for folder in (self.spam, self.trash):
            result = self.Folder.get_messages(
                folder_id=folder.id, search='00627', search_everywhere=True)
            self.assertTrue(all(row['folder_id'] == folder.id for row in result['messages']))
            self.assertEqual(result['scope'], 'folder')

    def test_no_search_no_scope(self):
        self._message(self.inbox, 'Письмо', day=5)
        result = self.Folder.get_messages(folder_id=self.inbox.id, search_everywhere=True)
        self.assertFalse(result['scope'])
        self.assertEqual(len(result['messages']), 1)

    def test_unified_search_everywhere_reaches_only_own_mailboxes(self):
        stranger = self.env['mail.client.account'].create({
            'name': 'Чужой', 'email': 'other@example.org', 'server_id': self.server.id,
        })
        stranger_inbox = self.Folder.create({
            'name': 'INBOX', 'account_id': stranger.id, 'imap_path': 'INBOX', 'role': 'inbox',
        })
        self._message(self.sent, 'Счёт 00627 наш', day=5)
        self._message(stranger_inbox, 'Счёт 00627 чужой', day=6, account=stranger)
        result = self.Folder.get_messages(
            unified=True, search='00627', search_everywhere=True)
        self.assertEqual([row['subject'] for row in result['messages']], ['Счёт 00627 наш'])
        self.assertEqual(result['scope'], 'everywhere')

    def test_copies_in_two_folders_are_one_row(self):
        """Наше письмо лежит и во «Входящих», и в «Отправленных» — одна строка,
        и на границе страниц тоже (страница по одной строке)."""
        self._message(self.inbox, 'Счёт 00627', day=5, message_id='<same@x>')
        self._message(self.sent, 'Счёт 00627', day=5, message_id='<same@x>')
        self._message(self.drawings, 'Счёт 00627 другой', day=3)
        whole = self.Folder.get_messages(
            folder_id=self.inbox.id, search='00627', search_everywhere=True)
        self.assertEqual(len(whole['messages']), 2)

        seen, before, before_id = [], None, None
        for _page in range(6):
            result = self.Folder.get_messages(
                folder_id=self.inbox.id, search='00627', search_everywhere=True,
                limit=1, before=before, before_id=before_id)
            seen += [row['subject'] for row in result['messages']]
            if not result['has_more']:
                break
            last = result['messages'][-1]
            before, before_id = last['date'], last['id']
        self.assertEqual(seen, ['Счёт 00627', 'Счёт 00627 другой'])

    def test_copy_in_inbox_wins(self):
        """Доводка шага 41: из копий «Входящие + Отправленные» остаётся копия
        во «Входящих» — и когда у копии в «Отправленных» id больше (так почти
        всегда на стенде). Её видно в самой папке и её считает число папки:
        значки строки и открытие строки гасят именно её. Страницами по одной
        строке — тоже ровно раз."""
        inbox_copy = self._message(self.inbox, 'Счёт 00627', day=5,
                                   message_id='<same@x>', seen=False)
        self._message(self.sent, 'Счёт 00627', day=5, message_id='<same@x>')
        other = self._message(self.drawings, 'Счёт 00627 другой', day=5)
        result = self.Folder.get_messages(
            folder_id=self.sent.id, search='00627', search_everywhere=True)
        rows = {row['id']: row for row in result['messages']}
        self.assertEqual(set(rows), {inbox_copy.id, other.id})
        self.assertEqual(rows[inbox_copy.id]['folder_id'], self.inbox.id)
        self.assertFalse(rows[inbox_copy.id]['flag_seen'], 'строка жирная, как во «Входящих»')

        seen, before, before_id = [], None, None
        for _page in range(6):
            page = self.Folder.get_messages(
                folder_id=self.sent.id, search='00627', search_everywhere=True,
                limit=1, before=before, before_id=before_id)
            seen += [row['id'] for row in page['messages']]
            if not page['has_more'] or not page['messages']:
                break
            last = page['messages'][-1]
            before, before_id = last['date'], last['id']
        self.assertEqual(seen, [other.id, inbox_copy.id])

    # ------------------------------------------------------------------
    # Б1: «Загрузить ещё» на равных датах
    # ------------------------------------------------------------------
    def _pages(self, threaded, key_of):
        rows, before, before_id = [], None, None
        for _page in range(10):
            result = self.Folder.get_messages(
                folder_id=self.inbox.id, threaded=threaded, limit=1,
                before=before, before_id=before_id)
            rows += result['messages']
            if not result['has_more'] or not result['messages']:
                break
            last = result['messages'][-1]
            before, before_id = last['date'], key_of(last)
        return rows

    def test_load_more_keeps_letters_with_equal_dates(self):
        """Три письма с одной датой, страница по одному: каждое ровно раз, по
        убыванию id. Раньше (ключ — только дата) приходило одно."""
        ids = [self._message(self.inbox, 'Письмо %s' % n, day=5).id for n in range(3)]
        rows = self._pages(False, lambda row: row['id'])
        self.assertEqual([row['id'] for row in rows], sorted(ids, reverse=True))

    def test_load_more_keeps_conversations_with_equal_dates(self):
        for n in range(3):
            self._message(self.inbox, 'Переписка %s' % n, day=5, key='<eq%s@x>' % n)
        self._message(self.inbox, 'Старая', day=1, key='<old@x>')
        rows = self._pages(True, lambda row: row['thread_max_id'])
        keys = [row['thread_key'] for row in rows]
        self.assertEqual(len(keys), 4)
        self.assertEqual(len(set(keys)), 4, 'Ни одна переписка не повторилась.')
        self.assertEqual(keys[-1], '<old@x>')
        # Порядок равных определён: id:max по убыванию.
        self.assertEqual(keys[:3], ['<eq2@x>', '<eq1@x>', '<eq0@x>'])

    def test_old_client_without_second_key_still_pages(self):
        self._message(self.inbox, 'Новое', day=6)
        self._message(self.inbox, 'Старое', day=2)
        first = self.Folder.get_messages(folder_id=self.inbox.id, limit=1)
        second = self.Folder.get_messages(
            folder_id=self.inbox.id, limit=1, before=first['messages'][0]['date'])
        self.assertEqual([r['subject'] for r in first['messages'] + second['messages']],
                         ['Новое', 'Старое'])

    def test_thread_row_carries_the_page_key(self):
        older = self._message(self.inbox, 'Первое', day=1, key='<k@x>')
        newer = self._message(self.sent, 'Ответ', day=2, key='<k@x>')
        row = self.Folder.get_messages(folder_id=self.inbox.id, threaded=True)['messages'][0]
        # Ключ — по письмам СПИСКА (папки), а не всей переписки.
        self.assertEqual(row['thread_max_id'], older.id)
        self.assertNotEqual(row['thread_max_id'], newer.id)

    # ------------------------------------------------------------------
    # строка и папки
    # ------------------------------------------------------------------
    def test_row_names_its_folder(self):
        message = self._message(self.drawings, 'Чертёж', day=5)
        row = self.Folder.get_messages(folder_id=self.drawings.id)['messages'][0]
        self.assertEqual(row['id'], message.id)
        self.assertEqual(row['folder_id'], self.drawings.id)

    def test_folder_total_in_inbox_state(self):
        self._message(self.drawings, 'Чертёж', day=5)
        self.drawings._refresh_counters()
        self.trash._refresh_counters()
        state = self.env['mail.client.account'].get_inbox_state()
        account = next(a for a in state['accounts'] if a['id'] == self.account.id)
        totals = {f['id']: f['total'] for f in account['folders']}
        self.assertEqual(totals[self.drawings.id], 1)
        self.assertEqual(totals[self.trash.id], 0)

    def test_thread_rows_hook_gets_rows_and_members(self):
        self._message(self.inbox, 'Первое', day=1, key='<k@x>')
        reply = self._message(self.sent, 'Ответ', day=2, key='<k@x>')
        calls = []
        Message = type(self.Message)
        original = Message._decorate_thread_rows

        def spy(model, payload, members):
            calls.append((len(payload), set(members.ids)))
            return original(model, payload, members)

        with patch.object(Message, '_decorate_thread_rows', spy):
            self.Folder.get_messages(folder_id=self.inbox.id, threaded=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 1)
        self.assertIn(reply.id, calls[0][1], 'Письма переписки — по всему ящику.')
