# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Outbox behaviour for two-way synchronisation.

The rule these tests defend: a user action is applied locally at once and
carried to the server later, and the push always happens before the next
fetch so a stale server state cannot undo it.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..tools.imap_client import ImapError


class RecordingConnection:
    """Captures the IMAP commands the outbox issues."""

    def __init__(self, fail_with=None):
        self.selected = []
        self.stored = []
        self.moved = []
        self.expunged = []
        self.fail_with = fail_with
        self.supports_move = True
        self.capabilities = {'UIDPLUS', 'MOVE'}

    def select(self, path, readonly=True, uid_validity=None, mod_seq=None):
        self.selected.append((path, readonly))
        return {'uid_validity': 1, 'uid_next': 1, 'mod_seq': 0, 'exists': 0,
                'vanished': [], 'qresync_used': False}

    def store_flags(self, uid, flags, add=True):
        if self.fail_with:
            raise ImapError(self.fail_with)
        self.stored.append((uid, tuple(flags), add))

    def move(self, uid, target_path):
        if self.fail_with:
            raise ImapError(self.fail_with)
        self.moved.append((uid, target_path))

    def expunge(self, uid=None):
        self.expunged.append(uid)


@tagged('post_install', '-at_install')
class TestTwoWaySync(TransactionCase):

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
        cls.inbox = cls.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': cls.account.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })
        cls.trash = cls.env['mail.client.folder'].create({
            'name': 'Trash', 'account_id': cls.account.id,
            'imap_path': 'Trash', 'role': 'trash',
        })
        cls.archive = cls.env['mail.client.folder'].create({
            'name': 'Archive', 'account_id': cls.account.id,
            'imap_path': 'Archive', 'role': 'archive',
        })

    def _message(self, uid=1, **values):
        return self.env['mail.client.message'].create({
            'account_id': self.account.id,
            'folder_id': self.inbox.id,
            'imap_uid': uid,
            'subject': 'Hello',
            'email_from': 'someone@example.org',
            **values,
        })

    def _ops(self):
        return self.env['mail.client.sync.op'].search([('account_id', '=', self.account.id)])

    # ------------------------------------------------------------------
    def test_marking_read_applies_locally_at_once(self):
        message = self._message()
        message._set_flag('\\Seen', True)
        self.assertTrue(
            message.flag_seen,
            "The interface must not wait for IMAP before showing the change.",
        )
        self.assertTrue(message.is_dirty)

    def test_marking_read_queues_one_operation(self):
        message = self._message()
        message._set_flag('\\Seen', True)
        operation = self._ops()
        self.assertEqual(len(operation), 1)
        self.assertEqual(operation.op_type, 'set_flag')
        self.assertEqual(operation.payload['flags'], ['\\Seen'])
        self.assertEqual(operation.imap_uid, 1)

    def test_one_way_account_queues_nothing(self):
        self.account.sync_mode = 'one_way'
        message = self._message()
        message._set_flag('\\Seen', True)
        self.assertTrue(message.flag_seen)
        self.assertFalse(
            self._ops(),
            "A read-only account must never write back to the server.",
        )

    # ------------------------------------------------------------------
    # Read-only means read-only in both directions.
    #
    # Only the outbox entry used to be gated on the sync mode; the local unlink
    # happened either way. That removed the message from Odoo while leaving it
    # on the server - and because a folder resumes from uid_next, its UID is
    # never fetched again, so the mail was gone from Odoo for good.
    # ------------------------------------------------------------------
    def test_one_way_account_refuses_to_move(self):
        self.account.sync_mode = 'one_way'
        message = self._message()
        with self.assertRaises(UserError):
            message._move_to(self.archive)
        self.assertTrue(
            message.exists(),
            "Refusing the move must leave the message where it is.",
        )
        self.assertFalse(self._ops())

    def test_one_way_account_refuses_to_delete(self):
        self.account.sync_mode = 'one_way'
        message = self._message()
        with self.assertRaises(UserError):
            message._delete()
        self.assertTrue(message.exists())
        self.assertFalse(self._ops())

    def test_one_way_delete_inside_trash_is_refused_too(self):
        """The expunge branch skips _move_to, so it needs its own guard."""
        self.account.sync_mode = 'one_way'
        message = self._message(uid=7, folder_id=self.trash.id)
        with self.assertRaises(UserError):
            message._delete()
        self.assertTrue(message.exists())

    def test_one_way_refusal_names_the_setting_to_change(self):
        self.account.sync_mode = 'one_way'
        message = self._message()
        with self.assertRaises(UserError) as caught:
            message._delete()
        self.assertIn('Two-way', str(caught.exception))
        self.assertIn(self.account.email, str(caught.exception))

    def test_bulk_delete_is_refused_on_a_read_only_account(self):
        """The RPC entry point is reachable regardless of what the UI shows."""
        self.account.sync_mode = 'one_way'
        messages = self._message(uid=11) | self._message(uid=12)
        with self.assertRaises(UserError):
            self.env['mail.client.message'].delete_bulk(messages.ids)
        self.assertEqual(len(messages.exists()), 2)

    def test_push_selects_the_mailbox_writable(self):
        message = self._message()
        message._set_flag('\\Seen', True)
        connection = RecordingConnection()
        self._ops()._push(connection)
        self.assertEqual(
            connection.selected, [('INBOX', False)],
            "STORE needs a writable mailbox; EXAMINE would be rejected.",
        )
        self.assertEqual(connection.stored, [(1, ('\\Seen',), True)])
        self.assertEqual(self._ops().state, 'done')

    def test_unflagging_sends_a_removal(self):
        message = self._message(flag_flagged=True)
        message._set_flag('\\Flagged', False)
        connection = RecordingConnection()
        self._ops()._push(connection)
        self.assertEqual(connection.stored, [(1, ('\\Flagged',), False)])

    def test_move_queues_target_and_drops_local_row(self):
        message = self._message()
        message._move_to(self.archive)
        operation = self._ops()
        self.assertEqual(operation.op_type, 'move')
        self.assertEqual(operation.payload['target_path'], 'Archive')
        self.assertFalse(
            message.exists(),
            "The UID belongs to the old folder; the target resync recreates it.",
        )

    def test_delete_moves_to_trash_first(self):
        message = self._message()
        message._delete()
        operation = self._ops()
        self.assertEqual(operation.op_type, 'move')
        self.assertEqual(operation.payload['target_path'], 'Trash')

    def test_delete_inside_trash_expunges(self):
        message = self._message(uid=7, folder_id=self.trash.id)
        message._delete()
        operation = self._ops()
        self.assertEqual(
            operation.op_type, 'delete',
            "Deleting something already in Trash must actually remove it.",
        )
        connection = RecordingConnection()
        operation._push(connection)
        self.assertEqual(connection.expunged, [7])

    def test_failed_push_is_retried_then_given_up_on(self):
        message = self._message()
        message._set_flag('\\Seen', True)
        operation = self._ops()

        connection = RecordingConnection(fail_with="server exploded")
        for _attempt in range(4):
            operation._execute(connection)
            self.assertEqual(operation.state, 'pending')
        operation._execute(connection)
        self.assertEqual(
            operation.state, 'failed',
            "A permanently broken operation must stop retrying forever.",
        )
        self.assertEqual(operation.retry_count, 5)

    def test_vanished_message_is_not_treated_as_failure(self):
        message = self._message()
        message._move_to(self.archive)
        operation = self._ops()
        connection = RecordingConnection(fail_with="UID MOVE: NO no such message")
        operation._execute(connection)
        self.assertEqual(
            operation.state, 'done',
            "If the message is already gone, the intent is satisfied.",
        )

    def test_push_runs_before_fetch(self):
        """The ordering that makes the whole outbox design work."""
        message = self._message()
        message._set_flag('\\Seen', True)
        connection = RecordingConnection()
        self.account._push_pending_ops(connection)
        self.assertEqual(self._ops().state, 'done')
        self.assertFalse(
            message.is_dirty,
            "Once pushed, the message is no longer awaiting the server.",
        )
