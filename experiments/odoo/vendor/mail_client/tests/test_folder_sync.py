# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Folder synchronisation, driven by a stub connection.

No IMAP server is involved: the point is to pin down the sync state machine,
above all UIDVALIDITY invalidation (risk R5), which only shows up in
production after a server migration or a Maildir restore.
"""
from datetime import datetime
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..tools.imap_client import ImapError

# Parsed BODYSTRUCTURE output, as tools.bodystructure.parse_parts returns it.
PARTS_WITH_PDF = [
    {'part_number': '1', 'content_type': 'text/html', 'maintype': 'text',
     'subtype': 'html', 'encoding': '7bit', 'size': 300, 'charset': 'utf-8',
     'filename': '', 'disposition': '', 'content_id': '', 'is_attachment': False},
    {'part_number': '2', 'content_type': 'application/pdf', 'maintype': 'application',
     'subtype': 'pdf', 'encoding': 'base64', 'size': 52000, 'charset': '',
     'filename': 'invoice.pdf', 'disposition': 'attachment', 'content_id': '',
     'is_attachment': True},
]

PARTS_TEXT_ONLY = [
    {'part_number': '1', 'content_type': 'text/plain', 'maintype': 'text',
     'subtype': 'plain', 'encoding': '7bit', 'size': 120, 'charset': 'utf-8',
     'filename': '', 'disposition': '', 'content_id': '', 'is_attachment': False},
]


class StubConnection:
    """Minimal stand-in for ImapConnection."""

    def __init__(self, uid_validity=1, uid_next=1, mod_seq=0, exists=0,
                 headers=None, changed=None, vanished=None, all_uids=None,
                 supports_qresync=True, folders=None, structures=None,
                 structure_error=None):
        self.folders = folders or []
        # {uid: parts}, as ImapConnection.fetch_structures returns.
        self.structures = structures or {}
        self.structure_error = structure_error
        self.structure_calls = []
        self.uid_validity = uid_validity
        self.uid_next = uid_next
        self.mod_seq = mod_seq
        self.exists = exists
        self.headers = headers or []
        self.changed = changed or []
        self.vanished = vanished or []
        self.all_uids = all_uids or []
        self.supports_qresync = supports_qresync
        self.selected = []
        self.fetch_calls = []
        self.closed = False

    def list_folders(self):
        return list(self.folders)

    def close(self):
        self.closed = True

    def select(self, path, readonly=True, uid_validity=None, mod_seq=None):
        self.selected.append(path)
        return {
            'uid_validity': self.uid_validity,
            'uid_next': self.uid_next,
            'mod_seq': self.mod_seq,
            'exists': self.exists,
            'vanished': [],
            'qresync_used': False,
        }

    def fetch_headers(self, uid_from, uid_to='*'):
        self.fetch_calls.append((uid_from, uid_to))
        return list(self.headers)

    def fetch_structures(self, uids):
        self.structure_calls.append(sorted(uids))
        if self.structure_error:
            raise self.structure_error
        return {uid: self.structures[uid] for uid in uids if uid in self.structures}

    def fetch_flags_since(self, mod_seq):
        return list(self.changed), list(self.vanished)

    def search_all_uids(self):
        return list(self.all_uids)

    def search_since(self, since_date):
        return list(self.all_uids)


def make_header(uid, subject='Hello', flags=None, message_id=None):
    return {
        'uid': uid,
        'flags': flags if flags is not None else [],
        'size': 1024,
        'subject': subject,
        'email_from': 'sender@example.org',
        'email_to': 'me@example.org',
        'email_cc': '',
        'message_id': message_id or '<uid-%s@example.org>' % uid,
        'in_reply_to': '',
        'references': '',
        'date': datetime(2026, 8, 1, 10, 0, 0),
        'spam_score': None,
        'is_spam': False,
    }


@tagged('post_install', '-at_install')
class TestFolderSync(TransactionCase):

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
            'name': 'Test',
            'email': 'test@example.org',
            'server_id': cls.server.id,
            'sync_window_days': 0,
        })
        cls.folder = cls.env['mail.client.folder'].create({
            'name': 'INBOX',
            'account_id': cls.account.id,
            'imap_path': 'INBOX',
            'role': 'inbox',
        })

    # ------------------------------------------------------------------
    def test_first_sync_creates_messages(self):
        connection = StubConnection(
            uid_validity=100, uid_next=4,
            headers=[make_header(1), make_header(2), make_header(3)],
        )
        self.folder._sync_messages(connection)

        self.assertEqual(len(self.folder.message_ids), 3)
        self.assertEqual(self.folder.uid_validity, 100)
        self.assertEqual(self.folder.uid_next, 4)

    def test_trailing_message_is_not_duplicated(self):
        """"start:*" always returns the last message even when nothing is new."""
        connection = StubConnection(
            uid_validity=100, uid_next=3, exists=2,
            headers=[make_header(1), make_header(2)],
        )
        self.folder._sync_messages(connection)
        self.assertEqual(len(self.folder.message_ids), 2)

        # Second run: the server still reports UID 2 as the last message.
        connection.headers = [make_header(2)]
        self.folder._sync_messages(connection)
        self.assertEqual(
            len(self.folder.message_ids), 2,
            "Re-fetching the boundary UID must not create a duplicate.",
        )

    def test_uidvalidity_change_triggers_full_resync(self):
        connection = StubConnection(
            uid_validity=100, uid_next=3,
            headers=[make_header(1), make_header(2)],
        )
        self.folder._sync_messages(connection)
        original_ids = self.folder.message_ids.ids
        self.assertEqual(len(original_ids), 2)

        # The server was migrated: every stored UID is now meaningless.
        connection.uid_validity = 200
        connection.uid_next = 3
        connection.exists = 2
        connection.headers = [make_header(1, subject='Rebuilt'), make_header(2)]
        self.folder._sync_messages(connection)

        self.assertEqual(self.folder.uid_validity, 200)
        self.assertEqual(len(self.folder.message_ids), 2)
        self.assertFalse(
            set(self.folder.message_ids.ids) & set(original_ids),
            "Messages from the previous UIDVALIDITY must be discarded, not reused.",
        )

    def test_flag_changes_are_applied(self):
        connection = StubConnection(
            uid_validity=100, uid_next=2, mod_seq=10,
            headers=[make_header(1)],
        )
        self.folder._sync_messages(connection)
        message = self.folder.message_ids
        self.assertFalse(message.flag_seen)

        connection.mod_seq = 20
        connection.headers = []
        connection.changed = [{'uid': 1, 'flags': ['\\Seen', '\\Flagged']}]
        self.folder._sync_messages(connection)

        self.assertTrue(message.flag_seen)
        self.assertTrue(message.flag_flagged)

    def test_vanished_messages_are_removed(self):
        connection = StubConnection(
            uid_validity=100, uid_next=4, mod_seq=10,
            headers=[make_header(1), make_header(2), make_header(3)],
        )
        self.folder._sync_messages(connection)
        self.assertEqual(len(self.folder.message_ids), 3)

        connection.mod_seq = 20
        connection.headers = []
        connection.vanished = [2]
        self.folder._sync_messages(connection)

        self.assertEqual(self.folder.message_ids.mapped('imap_uid'), [3, 1])

    def test_uid_diff_fallback_without_qresync(self):
        connection = StubConnection(
            uid_validity=100, uid_next=4, mod_seq=0, exists=2,
            headers=[make_header(1), make_header(2), make_header(3)],
            supports_qresync=False,
        )
        self.folder._sync_messages(connection)
        self.assertEqual(len(self.folder.message_ids), 3)

        # Server now holds only UIDs 1 and 3; no CONDSTORE state to rely on.
        connection.headers = []
        connection.all_uids = [1, 3]
        connection.exists = 2
        self.folder._sync_messages(connection)

        self.assertEqual(sorted(self.folder.message_ids.mapped('imap_uid')), [1, 3])

    def test_flag_sync_cost_does_not_grow_with_the_mailbox(self):
        """Reconciling one changed flag must not read the whole folder.

        The naive version loaded every message of the folder on each sync, so
        a 20,000-message inbox paid for 20,000 rows to learn that one flag
        moved.
        """
        connection = StubConnection(
            uid_validity=100, uid_next=201, exists=200,
            headers=[make_header(uid) for uid in range(1, 201)],
        )
        self.folder._sync_messages(connection)
        self.assertEqual(len(self.folder.message_ids), 200)

        self.env.invalidate_all()
        # Constant regardless of how many messages the folder holds. Tight on
        # purpose: if this creeps up, the per-folder scan has come back.
        with self.assertQueryCount(__system__=5):
            self.folder._apply_flag_changes([{'uid': 42, 'flags': ['\\Seen']}])

        changed = self.env['mail.client.message'].search([
            ('folder_id', '=', self.folder.id), ('imap_uid', '=', 42),
        ])
        self.assertTrue(changed.flag_seen)

    def test_only_the_changed_message_is_written(self):
        connection = StubConnection(
            uid_validity=100, uid_next=4, exists=3,
            headers=[make_header(1), make_header(2), make_header(3)],
        )
        self.folder._sync_messages(connection)
        untouched = self.env['mail.client.message'].search([
            ('folder_id', '=', self.folder.id), ('imap_uid', '=', 3),
        ])
        before = untouched.write_date

        self.folder._apply_flag_changes([{'uid': 1, 'flags': ['\\Seen']}])
        untouched.invalidate_recordset(['write_date'])
        self.assertEqual(
            untouched.write_date, before,
            "Messages whose flags did not change must not be rewritten.",
        )

    def test_counters_are_refreshed(self):
        connection = StubConnection(
            uid_validity=100, uid_next=3,
            headers=[make_header(1, flags=['\\Seen']), make_header(2)],
        )
        self.folder._sync_messages(connection)

        self.assertEqual(self.folder.total_count, 2)
        self.assertEqual(self.folder.unread_count, 1)

    # ------------------------------------------------------------------
    # attachment information, read during the sync rather than on open
    # ------------------------------------------------------------------
    def test_sync_records_which_messages_carry_attachments(self):
        """Otherwise the list can only tell you about mail you already opened."""
        connection = StubConnection(
            uid_validity=100, uid_next=3,
            headers=[make_header(1), make_header(2)],
            structures={1: PARTS_WITH_PDF, 2: PARTS_TEXT_ONLY},
        )
        self.folder._sync_messages(connection)

        by_uid = {m.imap_uid: m for m in self.folder.message_ids}
        self.assertTrue(by_uid[1].has_attachment)
        self.assertFalse(by_uid[2].has_attachment)
        self.assertEqual(by_uid[1].structure_state, 'parsed')
        self.assertEqual(by_uid[2].structure_state, 'parsed')

    def test_structures_are_asked_for_once_per_batch(self):
        connection = StubConnection(
            uid_validity=100, uid_next=4,
            headers=[make_header(1), make_header(2), make_header(3)],
            structures={1: PARTS_TEXT_ONLY},
        )
        self.folder._sync_messages(connection)
        self.assertEqual(connection.structure_calls, [[1, 2, 3]])

    def test_structures_are_not_asked_for_when_nothing_is_new(self):
        connection = StubConnection(
            uid_validity=100, uid_next=3, exists=2,
            headers=[make_header(1), make_header(2)],
            structures={1: PARTS_TEXT_ONLY, 2: PARTS_TEXT_ONLY},
        )
        self.folder._sync_messages(connection)
        connection.structure_calls.clear()
        self.folder._sync_messages(connection)
        self.assertEqual(connection.structure_calls, [],
                         "Nothing new means nothing to describe.")

    def test_messages_still_arrive_when_the_structure_fetch_fails(self):
        """Attachment information is worth a round trip, not the mail itself."""
        connection = StubConnection(
            uid_validity=100, uid_next=3,
            headers=[make_header(1), make_header(2)],
            structure_error=ImapError("BODYSTRUCTURE not supported"),
        )
        self.folder._sync_messages(connection)

        self.assertEqual(len(self.folder.message_ids), 2)
        self.assertEqual(set(self.folder.message_ids.mapped('structure_state')),
                         {'unknown'},
                         "Left unknown so the backfill retries them.")

    # ------------------------------------------------------------------
    # backfill of messages stored before their structure was read
    # ------------------------------------------------------------------
    def _stored(self, uid, structure_state='unknown'):
        return self.env['mail.client.message'].create({
            'account_id': self.account.id, 'folder_id': self.folder.id,
            'imap_uid': uid, 'subject': 'Old %s' % uid,
            'date': datetime(2026, 8, 1, 10, 0, 0),
            'structure_state': structure_state,
        })

    def test_backfill_describes_messages_stored_earlier(self):
        old = self._stored(1)
        plain = self._stored(2)
        connection = StubConnection(structures={1: PARTS_WITH_PDF, 2: PARTS_TEXT_ONLY})

        self.assertEqual(self.folder._backfill_structures(connection), 2)
        self.assertTrue(old.has_attachment)
        self.assertFalse(plain.has_attachment)
        self.assertEqual(old.structure_state, 'parsed')

    def test_backfill_leaves_settled_messages_alone(self):
        self._stored(1, structure_state='parsed')
        connection = StubConnection(structures={1: PARTS_WITH_PDF})
        self.assertEqual(self.folder._backfill_structures(connection), 0)
        self.assertEqual(connection.structure_calls, [])

    def test_backfill_asks_only_for_the_uids_it_needs(self):
        """A range spanning the gaps would make the server describe everything."""
        self._stored(1)
        self._stored(5000)
        connection = StubConnection(structures={})
        self.folder._backfill_structures(connection)
        self.assertEqual(connection.structure_calls, [[1, 5000]])

    def test_backfill_gives_up_on_a_message_the_server_will_not_describe(self):
        """Otherwise it heads the queue for ever and the backfill never ends."""
        unreadable = self._stored(1)
        readable = self._stored(2)
        connection = StubConnection(structures={2: PARTS_TEXT_ONLY})

        self.assertEqual(self.folder._backfill_structures(connection), 1)
        self.assertEqual(unreadable.structure_state, 'failed')
        self.assertEqual(readable.structure_state, 'parsed')

        # Second pass: the one it could not read is not asked about again.
        connection.structure_calls.clear()
        self.assertEqual(self.folder._backfill_structures(connection), 0)
        self.assertEqual(connection.structure_calls, [])

    def test_backfill_retries_after_a_connection_failure(self):
        """A server that was unreachable said nothing about any message."""
        pending = self._stored(1)
        connection = StubConnection(structure_error=ImapError("connection reset"))

        self.assertEqual(self.folder._backfill_structures(connection), 0)
        self.assertEqual(pending.structure_state, 'unknown',
                         "Marking it failed would forget a message we never asked about.")

    def test_settled_account_opens_no_connection(self):
        """The steady state. This cron runs for ever; idle must cost nothing."""
        self._stored(1, structure_state='parsed')
        self._stored(2, structure_state='failed')
        with patch.object(type(self.account), '_open_connection') as opener:
            self.account._backfill_structures()
        opener.assert_not_called()

    def test_account_with_pending_messages_connects_once(self):
        self._stored(1)
        connection = StubConnection(structures={1: PARTS_WITH_PDF})
        # The method commits per folder so a late failure does not throw away
        # the folders already done. A test cursor refuses to commit, and the
        # broad except in _backfill_structures would swallow that refusal and
        # let this pass without ever reaching the code under test.
        with patch.object(self.env.cr, 'commit') as commit, \
             patch.object(type(self.account), '_open_connection',
                          return_value=connection) as opener:
            self.account._backfill_structures()

        self.assertEqual(opener.call_count, 1)
        self.assertEqual(connection.selected, ['INBOX'])
        self.assertTrue(self.folder.message_ids.has_attachment)
        self.assertEqual(commit.call_count, 1,
                         "Progress on a finished folder must be kept.")
        self.assertTrue(connection.closed)

    def test_backfill_does_not_commit_a_folder_it_did_nothing_to(self):
        self._stored(1)
        connection = StubConnection(structure_error=ImapError("unreachable"))
        with patch.object(self.env.cr, 'commit') as commit, \
             patch.object(type(self.account), '_open_connection',
                          return_value=connection):
            self.account._backfill_structures()
        commit.assert_not_called()

    def test_backfill_is_bounded(self):
        for uid in range(1, 6):
            self._stored(uid)
        connection = StubConnection(structures={uid: PARTS_TEXT_ONLY for uid in range(1, 6)})
        self.folder._backfill_structures(connection, limit=2)
        self.assertEqual(connection.structure_calls, [[4, 5]],
                         "Newest first: the mail somebody is most likely to look at.")

    def test_thread_key_follows_reference_chain(self):
        Message = self.env['mail.client.message']
        root = Message._compute_thread_key_value({
            'references': '', 'in_reply_to': '', 'message_id': '<root@example.org>',
        })
        reply = Message._compute_thread_key_value({
            'references': '<root@example.org> <second@example.org>',
            'in_reply_to': '<second@example.org>',
            'message_id': '<third@example.org>',
        })
        self.assertEqual(root, '<root@example.org>')
        self.assertEqual(
            reply, '<root@example.org>',
            "A reply must key off the first reference so the thread stays whole.",
        )

    def test_structure_is_fetched_for_a_message_whose_body_is_already_stored(self):
        """Messages read before attachments existed must still get their parts.

        Body and MIME structure are tracked separately; treating them as one
        left older messages with attachments that could never be opened.
        """
        message = self.env['mail.client.message'].create({
            'account_id': self.account.id,
            'folder_id': self.folder.id,
            'imap_uid': 99,
            'subject': 'Already read on the server',
            'body_html': '<p>already here</p>',
            'body_state': 'fetched',
            'structure_state': 'unknown',
            'has_attachment': True,
        })

        calls = []

        class StubBodyConnection:
            def select(self, path, readonly=True, uid_validity=None, mod_seq=None):
                return {}

            def fetch_structure(self, uid):
                calls.append(uid)
                return [
                    {'part_number': '1', 'content_type': 'text/html', 'maintype': 'text',
                     'subtype': 'html', 'encoding': '7bit', 'size': 10, 'charset': 'utf-8',
                     'filename': '', 'disposition': '', 'content_id': '',
                     'is_attachment': False},
                    {'part_number': '2', 'content_type': 'application/pdf',
                     'maintype': 'application', 'subtype': 'pdf', 'encoding': 'base64',
                     'size': 4096, 'charset': '', 'filename': 'invoice.pdf',
                     'disposition': 'attachment', 'content_id': '', 'is_attachment': True},
                ]

            def close(self):
                pass

        connection = StubBodyConnection()
        with patch.object(type(self.account), '_open_connection', return_value=connection):
            message._fetch_body()

        self.assertEqual(calls, [99], "The structure must be fetched even so.")
        self.assertEqual(message.structure_state, 'parsed')
        self.assertEqual(len(message.client_attachment_ids), 1)
        attachment = message.client_attachment_ids
        self.assertEqual(attachment.name, 'invoice.pdf')
        self.assertEqual(attachment.part_number, '2')
        self.assertEqual(
            message.body_html, '<p>already here</p>',
            "An already-stored body must not be re-downloaded or replaced.",
        )

    def test_inbox_is_subscribed_even_when_lsub_omits_it(self):
        """Dovecot's LSUB lists only explicitly subscribed mailboxes, and
        clients routinely never subscribe INBOX because it always exists."""
        connection = StubConnection(folders=[
            {'path': 'INBOX', 'delimiter': '/', 'flags': set(), 'subscribed': False},
            {'path': 'Sent', 'delimiter': '/', 'flags': {'\\SENT'}, 'subscribed': True},
        ])
        account = self.env['mail.client.account'].create({
            'name': 'Fresh', 'email': 'fresh@example.org', 'server_id': self.server.id,
        })
        account._sync_folders(connection)

        inbox = account.folder_ids.filtered(lambda f: f.role == 'inbox')
        self.assertTrue(inbox, "The inbox must be created.")
        self.assertTrue(
            inbox.subscribed,
            "An inbox that is not synchronised makes the whole client useless.",
        )

    def test_unsubscribing_a_folder_survives_resync(self):
        connection = StubConnection(folders=[
            {'path': 'INBOX', 'delimiter': '/', 'flags': set(), 'subscribed': True},
            {'path': 'Newsletters', 'delimiter': '/', 'flags': set(), 'subscribed': True},
        ])
        account = self.env['mail.client.account'].create({
            'name': 'Choice', 'email': 'choice@example.org', 'server_id': self.server.id,
        })
        account._sync_folders(connection)

        newsletters = account.folder_ids.filtered(lambda f: f.name == 'Newsletters')
        newsletters.subscribed = False
        account._sync_folders(connection)

        self.assertFalse(
            newsletters.subscribed,
            "Once the folder exists, the subscription is the user's choice, "
            "not something LSUB should overwrite on every sync.",
        )

    def test_folder_role_detection_prefers_special_use(self):
        Account = self.env['mail.client.account']
        self.assertEqual(Account._detect_folder_role('INBOX.Sent', {'\\SENT'}), 'sent')
        self.assertEqual(Account._detect_folder_role('INBOX', set()), 'inbox')
        self.assertEqual(Account._detect_folder_role('INBOX.Terkirim', set()), 'sent')
        self.assertEqual(Account._detect_folder_role('INBOX.Project X', set()), 'other')
