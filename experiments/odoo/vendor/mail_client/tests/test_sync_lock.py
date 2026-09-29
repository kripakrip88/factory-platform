# -*- coding: utf-8 -*-
"""ПРАВКА ПМК (шаг 22 плана, 30.09.2026): один проход по ящику в каждый момент.

Что защищаем:
• ящик, который синхронизирует другое соединение (крон, кнопка в другой
  вкладке, дочитка структур), второй проход пропускает: без входа на сервер,
  без записи в ящик, строкой INFO в журнале;
• кнопка «Синхронизировать» отвечает «занято» (busy), а не ошибкой;
• блокировка берётся и отпускается на ОДНОМ соединении — том, на котором
  идёт проход, — и отпускается всегда: после удачного прохода, после
  исключения и из прерванной транзакции (соединение Odoo возвращается в пул
  открытым, забытая блокировка заперла бы ящик для всех остальных);
• итог прохода фиксируется до снятия блокировки, а снимок базы проход
  берёт уже под ней (commit сразу после блокировки, REPEATABLE READ);
• дочитка структур отпускает ящик только с чистой транзакцией: папка,
  которая что-то записала (и одни 'failed'), фиксируется, неожиданная
  ошибка откатывается до снятия;
• сигнал шины и ответ кнопки говорят, изменилось ли что-то в письмах ящика
  и в каких папках.

Второе соединение — настоящее (self.registry.cursor()): тестовая транзакция
его не видит, но advisory-блокировка — просто пара чисел, запись ящика ей не
нужна. Отпускаем её там всегда (addCleanup), иначе соединение ушло бы в пул
с блокировкой.
"""
from collections import Counter
from unittest.mock import patch

import psycopg2

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.mail_client_account import MAILBOX_LOCK_KEY
from .test_folder_sync import StubConnection, make_header

LOGGER = 'odoo.addons.mail_client.models.mail_client_account'
INBOX = [{'path': 'INBOX', 'delimiter': '/', 'flags': set(), 'subscribed': True}]


@tagged('post_install', '-at_install')
class TestSyncLock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env['mail.client.server'].create({
            'name': 'Stub server',
            'imap_host': 'mail.example.org',
            'auth_mode': 'master',
            'master_user': 'master',
        })
        cls.account = cls.env['mail.client.account'].create({
            'name': 'Lock',
            'email': 'lock@example.org',
            'server_id': cls.server.id,
            'user_id': cls.env.ref('base.user_admin').id,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _other_connection(self):
        """A real second connection, as the cron's or another request's."""
        cr = self.registry.cursor()
        self.addCleanup(cr.close)
        # Runs before close (cleanups are LIFO): never give a connection
        # back to the pool still holding a lock.
        self.addCleanup(cr.execute, "SELECT pg_advisory_unlock_all()")
        return cr

    def _hold_lock(self, account=None):
        cr = self._other_connection()
        cr.execute("SELECT pg_try_advisory_lock(%s, %s)",
                   (MAILBOX_LOCK_KEY, (account or self.account).id))
        self.assertTrue(cr.fetchone()[0], "The mailbox must be free to begin with.")
        return cr

    def _held_here(self, account=None):
        """Whether THIS test connection holds the mailbox lock."""
        self.env.cr.execute("""
            SELECT count(*) FROM pg_locks
             WHERE locktype = 'advisory' AND classid = %s AND objid = %s
               AND objsubid = 2 AND pid = pg_backend_pid()
        """, (MAILBOX_LOCK_KEY, (account or self.account).id))
        return bool(self.env.cr.fetchone()[0])

    def _free_for(self, cr, account=None):
        """Whether another connection can take the mailbox now."""
        account_id = (account or self.account).id
        cr.execute("SELECT pg_try_advisory_lock(%s, %s)", (MAILBOX_LOCK_KEY, account_id))
        free = cr.fetchone()[0]
        if free:
            cr.execute("SELECT pg_advisory_unlock(%s, %s)", (MAILBOX_LOCK_KEY, account_id))
        return free

    def _connection(self, uids=(), exists=None):
        """A server whose INBOX holds ``uids``."""
        uids = list(uids)
        return StubConnection(
            folders=INBOX, uid_validity=1,
            uid_next=max(uids, default=0) + 1,
            exists=len(uids) if exists is None else exists,
            headers=[make_header(uid) for uid in uids],
            all_uids=uids, supports_qresync=False,
        )

    def _run(self, connection):
        """One pass over ``connection``; the per-folder commits are patched."""
        with patch.object(self.env.cr, 'commit'), \
             patch.object(type(self.account), '_open_connection', return_value=connection):
            return self.account._sync()

    def _spy_bus(self):
        sent = []
        Partner = type(self.env['res.partner'])
        original = Partner._bus_send

        def spy(records, notification_type, message, *args, **kwargs):
            if notification_type == 'mail_client.sync':
                sent.append(dict(message))
            return original(records, notification_type, message, *args, **kwargs)

        self.patch(Partner, '_bus_send', spy)
        return sent

    # ------------------------------------------------------------------
    # the pass
    # ------------------------------------------------------------------
    def test_busy_mailbox_is_skipped(self):
        self._hold_lock()
        with patch.object(type(self.account), '_open_connection') as opener, \
             self.assertLogs(LOGGER, level='INFO') as logs:
            result = self.account._sync()
        self.assertIs(result, False)
        opener.assert_not_called()
        self.assertEqual(self.account.state, 'draft', "A skipped pass writes nothing.")
        self.assertIn('already being synchronised', '\n'.join(logs.output))
        self.assertFalse(self._held_here(), "Not taken, so nothing to hold.")

    def test_cron_moves_on_to_the_next_mailbox(self):
        other = self.env['mail.client.account'].create({
            'name': 'Free', 'email': 'free@example.org', 'server_id': self.server.id,
        })
        self._hold_lock()
        synced = []
        original = type(self.account)._sync_pass

        def spy(records):
            synced.append(records.id)
            return original(records)

        self.patch(type(self.account), '_sync_pass', spy)
        # Only these two: a copied database may hold real mailboxes.
        with patch.object(self.env.cr, 'commit'), \
             patch.object(type(self.account), '_syncable_accounts',
                          return_value=self.account | other), \
             patch.object(type(self.account), '_open_connection',
                          return_value=self._connection()):
            self.env['mail.client.account']._cron_sync_all()
        self.assertIn(other.id, synced)
        self.assertNotIn(self.account.id, synced)

    def test_lock_is_taken_and_released_on_the_pass_connection(self):
        seen = {}
        original = type(self.account)._sync_pass

        def spy(records):
            seen['held'] = self._held_here()
            return original(records)

        self.patch(type(self.account), '_sync_pass', spy)
        other = self._other_connection()
        result = self._run(self._connection([1]))

        self.assertTrue(seen['held'], "The pass runs on the connection holding the lock.")
        self.assertFalse(self._held_here(), "Released after the pass.")
        self.assertTrue(self._free_for(other), "Another connection can take it now.")
        self.assertTrue(result['changed'])
        self.assertEqual(self.account.state, 'connected', self.account.error_message)

    def test_result_is_committed_before_the_lock_is_released(self):
        held_at_commit = []

        def commit():
            held_at_commit.append(self._held_here())

        with patch.object(self.env.cr, 'commit', side_effect=commit), \
             patch.object(type(self.account), '_open_connection',
                          return_value=self._connection([1])):
            self.account._sync()
        self.assertTrue(held_at_commit)
        self.assertTrue(held_at_commit[-1],
                        "The next pass would otherwise wait on our uncommitted mailbox row.")
        self.assertFalse(self._held_here())

    def test_lock_is_released_when_the_pass_blows_up(self):
        # commit: the fresh snapshot taken under the lock, before the pass.
        with patch.object(self.env.cr, 'commit'), \
             patch.object(type(self.account), '_sync_pass', side_effect=RuntimeError("boom")), \
             self.assertRaises(RuntimeError):
            self.account._sync()
        self.assertFalse(self._held_here())

    def test_pass_starts_a_fresh_snapshot_under_the_lock(self):
        """REPEATABLE READ: the snapshot is taken by the first statement of
        the transaction, and every caller runs one before the lock. A commit
        right after the lock, before the pass, starts the pass on a snapshot
        that already holds the previous pass's result."""
        events = []
        original = type(self.account)._sync_pass

        def spy(records):
            events.append('pass')
            return original(records)

        self.patch(type(self.account), '_sync_pass', spy)
        with patch.object(self.env.cr, 'commit',
                          side_effect=lambda: events.append(('commit', self._held_here()))), \
             patch.object(type(self.account), '_open_connection',
                          return_value=self._connection([1])):
            self.account._sync()
        self.assertEqual(events[0], ('commit', True),
                         "First a commit, with the mailbox already held.")
        self.assertEqual(events[1], 'pass')

    def test_lock_is_released_from_an_aborted_transaction(self):
        """An error is on its way up and the transaction refuses every
        statement: the unlock still has to happen, on that same connection."""
        cr = self._other_connection()
        cr.execute("SELECT pg_try_advisory_lock(%s, %s)", (MAILBOX_LOCK_KEY, self.account.id))
        self.assertTrue(cr.fetchone()[0])
        with self.assertRaises(psycopg2.Error):
            cr.execute("SELECT 1/0", log_exceptions=False)
        self.account._unlock_mailbox(cr)
        self.assertTrue(self._free_for(self.env.cr))

    def test_structure_backfill_waits_for_the_sync(self):
        folder = self.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': self.account.id, 'imap_path': 'INBOX',
            'role': 'inbox',
        })
        self.env['mail.client.message'].create({
            'account_id': self.account.id, 'folder_id': folder.id, 'imap_uid': 1,
            'subject': 'Old', 'structure_state': 'unknown',
        })
        other = self._hold_lock()
        with patch.object(type(self.account), '_open_connection') as opener, \
             self.assertLogs(LOGGER, level='INFO'):
            self.account._backfill_structures()
        opener.assert_not_called()

        other.execute("SELECT pg_advisory_unlock_all()")
        connection = self._connection()
        with patch.object(self.env.cr, 'commit'), \
             patch.object(type(self.account), '_open_connection', return_value=connection):
            self.account._backfill_structures()
        self.assertEqual(connection.selected, ['INBOX'], "Free again: the backfill runs.")
        self.assertFalse(self._held_here())

    def _backfill_folder(self):
        folder = self.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': self.account.id, 'imap_path': 'INBOX',
            'role': 'inbox',
        })
        message = self.env['mail.client.message'].create({
            'account_id': self.account.id, 'folder_id': folder.id, 'imap_uid': 1,
            'subject': 'Old', 'structure_state': 'unknown',
        })
        return folder, message

    def test_backfill_commits_a_folder_that_only_marked_failures(self):
        """The server answered for the batch but not about this message: it is
        marked 'failed' and nothing is settled. The write is still committed,
        and under the lock: released with it pending, the next pass taking
        the mailbox would run into these rows."""
        _folder, message = self._backfill_folder()
        Folder = type(self.env['mail.client.folder'])
        held_at_commit = []
        # An answer, just not about uid 1 (the stub server only ever answers
        # about the UIDs it was asked for).
        with patch.object(Folder, '_fetch_structures', return_value={99: []}), \
             patch.object(self.env.cr, 'commit',
                          side_effect=lambda: held_at_commit.append(self._held_here())), \
             patch.object(type(self.account), '_open_connection',
                          return_value=self._connection()):
            self.account._backfill_structures()
        self.assertEqual(message.structure_state, 'failed')
        self.assertEqual(held_at_commit, [True])
        self.assertFalse(self._held_here())

    def test_backfill_rolls_back_before_releasing_on_an_unexpected_error(self):
        self._backfill_folder()
        Folder = type(self.env['mail.client.folder'])
        held_at_rollback = []
        with patch.object(Folder, '_backfill_structures_batch',
                          side_effect=RuntimeError("boom")), \
             patch.object(self.env.cr, 'commit'), \
             patch.object(self.env.cr, 'rollback',
                          side_effect=lambda: held_at_rollback.append(self._held_here())), \
             patch.object(type(self.account), '_open_connection',
                          return_value=self._connection()), \
             self.assertLogs(LOGGER, level='ERROR'):
            self.account._backfill_structures()
        self.assertEqual(held_at_rollback, [True], "Rolled back first, then released.")
        self.assertFalse(self._held_here())

    # ------------------------------------------------------------------
    # the Sync button
    # ------------------------------------------------------------------
    def test_button_answers_busy_instead_of_failing(self):
        self._hold_lock()
        with patch.object(type(self.account), '_open_connection') as opener:
            result = self.env['mail.client.account'].sync_account(self.account.id)
        opener.assert_not_called()
        self.assertTrue(result['busy'])
        self.assertFalse(result['changed'])
        self.assertEqual(result['folder_ids'], [])
        self.assertNotEqual(result['state'], 'error')

    def test_button_says_whether_anything_changed(self):
        Account = self.env['mail.client.account']
        with patch.object(self.env.cr, 'commit'), \
             patch.object(type(self.account), '_open_connection',
                          return_value=self._connection([1, 2])):
            first = Account.sync_account(self.account.id)
        self.assertEqual((first['busy'], first['changed'], first['state']),
                         (False, True, 'connected'))
        with patch.object(self.env.cr, 'commit'), \
             patch.object(type(self.account), '_open_connection',
                          return_value=self._connection([1, 2])):
            second = Account.sync_account(self.account.id)
        self.assertEqual((second['busy'], second['changed']), (False, False))

    def test_form_button_reports_a_busy_mailbox(self):
        self._hold_lock()
        action = self.account.action_sync_now()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn(self.account.email, action['params']['message'])

    # ------------------------------------------------------------------
    # the bus signal
    # ------------------------------------------------------------------
    def test_bus_signal_says_what_changed(self):
        sent = self._spy_bus()

        self._run(self._connection([1, 2]))
        self.assertEqual(len(sent), 1, "One signal per pass.")
        inbox = self.account.folder_ids.filtered(lambda f: f.imap_path == 'INBOX')
        self.assertEqual(
            {key: sent[-1][key]
             for key in ('account_id', 'state', 'changed', 'new', 'removed', 'folder_ids')},
            {'account_id': self.account.id, 'state': 'connected', 'changed': True,
             'new': 2, 'removed': 0, 'folder_ids': inbox.ids})

        self._run(self._connection([1, 2]))
        self.assertFalse(sent[-1]['changed'], "Nothing new: the list is not reloaded.")
        self.assertEqual((sent[-1]['new'], sent[-1]['removed'], sent[-1]['flags']), (0, 0, 0))
        self.assertEqual(sent[-1]['folder_ids'], [])

        self._run(self._connection([1]))
        self.assertTrue(sent[-1]['changed'])
        self.assertEqual(sent[-1]['removed'], 1, "Deleted on the server.")

    def test_summary_names_only_the_folders_that_changed(self):
        """New mail in Spam must not make the open Inbox re-read its list."""
        summary = self.env['mail.client.account']._change_summary(
            {7: Counter(new=3), 8: Counter(new=0, flags=0), 9: Counter(flags=1)})
        self.assertEqual(summary, {'new': 3, 'removed': 0, 'flags': 1,
                                   'changed': True, 'folder_ids': [7, 9]})

    def test_failed_pass_still_signals_its_state(self):
        sent = self._spy_bus()
        with patch.object(self.env.cr, 'commit'), \
             patch.object(type(self.account), '_open_connection',
                          side_effect=UserError("no route to host")):
            result = self.account._sync()
        self.assertEqual(self.account.state, 'error')
        self.assertEqual(sent[-1]['state'], 'error')
        self.assertFalse(sent[-1]['changed'])
        self.assertFalse(result['changed'])
        self.assertFalse(self._held_here())

    def test_signal_without_a_pass_counts_as_changed(self):
        sent = self._spy_bus()
        self.account._notify_bus()
        self.assertTrue(sent[-1]['changed'],
                        "Unknown is treated as changed: a spare refresh is harmless.")
