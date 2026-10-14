# -*- coding: utf-8 -*-
"""Дочитка текста писем (шаг 1 редизайна почты, 14.10.2026): текст сохраняется
заранее, одним входом в ящик на пачку, новые — первыми, без спама и корзины,
только просмотр (EXAMINE)."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

TEXT_PART = [
    {'part_number': '1', 'content_type': 'text/plain', 'maintype': 'text',
     'subtype': 'plain', 'encoding': '7bit', 'size': 120, 'charset': 'utf-8',
     'filename': '', 'disposition': '', 'content_id': '', 'is_attachment': False},
]


class StubConnection:
    def __init__(self):
        self.selects = []
        self.parts = []
        self.closed = False

    def select(self, path, readonly=True, **kw):
        self.selects.append((path, readonly))
        return {}

    def fetch_structure(self, uid):
        return TEXT_PART

    def fetch_part(self, uid, part_number, encoding=''):
        self.parts.append(uid)
        return ("Добрый день! Просим рассчитать траверсу %s." % uid).encode()

    def fetch_body(self, uid):
        return '', '', False

    def close(self):
        self.closed = True


@tagged("post_install", "-at_install")
class TestPrefetchBodies(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env['mail.client.server'].create({
            'name': 'Stub', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master'})
        cls.account = cls.env['mail.client.account'].create({
            'name': 'Prefetch', 'email': 'prefetch@example.org',
            'server_id': server.id, 'sync_window_days': 0})
        Folder = cls.env['mail.client.folder']
        cls.inbox = Folder.create({'name': 'INBOX', 'account_id': cls.account.id,
                                   'imap_path': 'INBOX', 'role': 'inbox'})
        cls.spam = Folder.create({'name': 'Spam', 'account_id': cls.account.id,
                                  'imap_path': 'Spam', 'role': 'spam'})
        now = fields.Datetime.now()
        Message = cls.env['mail.client.message']
        cls.fresh = Message.create({'account_id': cls.account.id, 'folder_id': cls.inbox.id,
                                    'imap_uid': 11, 'subject': 'Свежее',
                                    'date': now - timedelta(hours=1)})
        cls.month = Message.create({'account_id': cls.account.id, 'folder_id': cls.inbox.id,
                                    'imap_uid': 10, 'subject': 'Месяц назад',
                                    'date': now - timedelta(days=30)})
        cls.old = Message.create({'account_id': cls.account.id, 'folder_id': cls.inbox.id,
                                  'imap_uid': 5, 'subject': 'Полгода назад',
                                  'date': now - timedelta(days=200)})
        cls.junk = Message.create({'account_id': cls.account.id, 'folder_id': cls.spam.id,
                                   'imap_uid': 3, 'subject': 'Спам',
                                   'date': now - timedelta(hours=2)})

    def _run(self, **kw):
        connection = StubConnection()
        Account = type(self.account)
        with patch.object(Account, '_open_connection', return_value=connection), \
                patch.object(Account, '_try_lock_mailbox', return_value=True), \
                patch.object(Account, '_unlock_mailbox', return_value=None), \
                patch.object(self.env.cr, 'commit', lambda: None), \
                patch.object(self.env.cr, 'rollback', lambda: None):
            done = self.account._prefetch_bodies(**kw)
        return done, connection

    def test_recent_mail_prefetched_without_spam_and_old(self):
        done, connection = self._run(days=90, limit=60)
        self.assertEqual(done, 2)
        self.assertEqual(self.fresh.body_state, 'fetched')
        self.assertEqual(self.month.body_state, 'fetched')
        self.assertIn("траверсу 11", self.fresh.body_html)
        self.assertTrue(self.fresh.preview, "Начало текста — для строки списка.")
        self.assertEqual(self.old.body_state, 'header_only', "Старше окна — не дочитываем.")
        self.assertEqual(self.junk.body_state, 'header_only', "Спам не дочитываем.")
        # Один вход в ящик, только просмотр (EXAMINE), новое — первым.
        self.assertEqual(connection.selects, [('INBOX', True)])
        self.assertEqual(connection.parts, [11, 10])
        self.assertTrue(connection.closed)

    def test_batch_limit_newest_first(self):
        done, connection = self._run(days=90, limit=1)
        self.assertEqual(done, 1)
        self.assertEqual(self.fresh.body_state, 'fetched')
        self.assertEqual(self.month.body_state, 'header_only')

    def test_cron_exists(self):
        cron = self.env.ref('pmk_mail_ui.ir_cron_pmk_mail_prefetch_bodies')
        self.assertTrue(cron.active)
        self.assertEqual((cron.interval_number, cron.interval_type), (2, 'minutes'))
