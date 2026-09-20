# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Protocol-level parsing.

These run without a database or a mail server: they are pure functions over
bytes, which is exactly the part that real-world mail breaks (risk R8).
"""
import email

from odoo.tests import TransactionCase, tagged

from ..tools.imap_client import (
    ImapConnection, ImapError, _compact_uid_set, _iter_fetch_items,
    _iter_fetch_records, _parse_uid_set,
)
from ..tools import bodystructure
from ..tools.imap_utf7 import imap_utf7_decode, imap_utf7_encode


@tagged('post_install', '-at_install')
class TestImapUtf7(TransactionCase):

    def test_ascii_passthrough(self):
        self.assertEqual(imap_utf7_encode('INBOX'), 'INBOX')
        self.assertEqual(imap_utf7_decode('INBOX'), 'INBOX')

    def test_roundtrip_non_ascii(self):
        for name in ('Entwürfe', 'Papierkorb', 'Arsip Terkirim', '受信箱'):
            self.assertEqual(imap_utf7_decode(imap_utf7_encode(name)), name)

    def test_known_encoding(self):
        # The canonical example from RFC 3501.
        self.assertEqual(imap_utf7_decode('~peter/mail/&U,BTFw-/&ZeVnLIqe-'),
                         '~peter/mail/台北/日本語')

    def test_literal_ampersand(self):
        self.assertEqual(imap_utf7_encode('Bills & Receipts'), 'Bills &- Receipts')
        self.assertEqual(imap_utf7_decode('Bills &- Receipts'), 'Bills & Receipts')

    def test_malformed_name_does_not_raise(self):
        # A truncated shift sequence must degrade, not crash the folder sync.
        self.assertTrue(imap_utf7_decode('Broken&ZeV'))


@tagged('post_install', '-at_install')
class TestImapResponseParsing(TransactionCase):

    def test_parse_uid_set_ranges(self):
        self.assertEqual(_parse_uid_set(b'41,43:46,50'), [41, 43, 44, 45, 46, 50])

    def test_parse_uid_set_earlier_marker(self):
        self.assertEqual(_parse_uid_set(b'(EARLIER) 3:5'), [3, 4, 5])

    def test_parse_uid_set_reversed_range(self):
        self.assertEqual(_parse_uid_set(b'8:6'), [6, 7, 8])

    def test_parse_uid_set_garbage_is_skipped(self):
        self.assertEqual(_parse_uid_set(b'1,,abc,3'), [1, 3])

    def test_parse_list_line(self):
        parsed = ImapConnection._parse_list_line(
            b'(\\HasNoChildren \\Sent) "." "INBOX.Sent"'
        )
        self.assertEqual(parsed['path'], 'INBOX.Sent')
        self.assertEqual(parsed['delimiter'], '.')
        self.assertIn('\\SENT', parsed['flags'])

    def test_parse_list_line_decodes_utf7(self):
        parsed = ImapConnection._parse_list_line(
            b'(\\HasNoChildren) "/" "Entw&APw-rfe"'
        )
        self.assertEqual(parsed['path'], 'Entwürfe')

    def test_iter_fetch_items_skips_closing_paren(self):
        response = [(b'1 (UID 5 {12}', b'Subject: hi'), b')']
        items = list(_iter_fetch_items(response))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], b'Subject: hi')

    # ------------------------------------------------------------------
    # grouping a ranged FETCH back into messages
    # ------------------------------------------------------------------
    def test_iter_fetch_records_one_per_message(self):
        response = [
            b'1 (UID 10 BODYSTRUCTURE ("TEXT" "PLAIN" NIL NIL NIL "7BIT" 10 1))',
            b'2 (UID 11 BODYSTRUCTURE ("TEXT" "HTML" NIL NIL NIL "7BIT" 20 2))',
        ]
        records = list(_iter_fetch_records(response))
        self.assertEqual([uid for uid, _raw in records], [10, 11])
        self.assertIn(b'PLAIN', records[0][1])
        self.assertIn(b'HTML', records[1][1])

    def test_iter_fetch_records_rejoins_a_literal(self):
        """A literal splits one message over several items; it is still one message."""
        response = [
            (b'1 (UID 10 BODYSTRUCTURE ("APPLICATION" "PDF" ("NAME" {11}', b'invoice.pdf'),
            b') NIL NIL "BASE64" 900 NIL NIL NIL NIL)',
            b'2 (UID 11 BODYSTRUCTURE ("TEXT" "PLAIN" NIL NIL NIL "7BIT" 10 1))',
        ]
        records = list(_iter_fetch_records(response))
        self.assertEqual([uid for uid, _raw in records], [10, 11])
        # The literal is quoted back into place, so the tokenizer sees a string.
        self.assertIn(b'"invoice.pdf"', records[0][1])
        # ...and the tail that followed it belongs to the same message.
        self.assertIn(b'BASE64', records[0][1])

    def test_iter_fetch_records_ignores_a_uid_inside_a_literal(self):
        """A filename that reads like a UID must not start a new message."""
        response = [
            (b'1 (UID 10 BODYSTRUCTURE ("APPLICATION" "PDF" ("NAME" {13}', b'UID 999 x.pdf'),
            b') NIL NIL "BASE64" 900 NIL NIL NIL NIL)',
        ]
        records = list(_iter_fetch_records(response))
        self.assertEqual([uid for uid, _raw in records], [10])

    def test_iter_fetch_records_ignores_a_leading_stray(self):
        records = list(_iter_fetch_records([b')', b'1 (UID 7 BODYSTRUCTURE NIL)']))
        self.assertEqual([uid for uid, _raw in records], [7])

    # ------------------------------------------------------------------
    # building a uid-set
    # ------------------------------------------------------------------
    def test_compact_uid_set_collapses_runs(self):
        self.assertEqual(_compact_uid_set([4, 5, 6, 9]), '4:6,9')
        self.assertEqual(_compact_uid_set([3]), '3')
        self.assertEqual(_compact_uid_set([7, 3, 5]), '3,5,7')

    def test_compact_uid_set_handles_nothing(self):
        self.assertEqual(_compact_uid_set([]), '')
        self.assertEqual(_compact_uid_set(None), '')

    def test_compact_uid_set_deduplicates(self):
        self.assertEqual(_compact_uid_set([2, 2, 3]), '2:3')

    def test_compact_uid_set_roundtrips(self):
        """It is the inverse of the parser the same module already uses."""
        uids = [1, 2, 3, 10, 42, 43, 44, 100]
        self.assertEqual(_parse_uid_set(_compact_uid_set(uids)), uids)


@tagged('post_install', '-at_install')
class TestFetchStructures(TransactionCase):
    """Reading attachment information for a whole batch in one command.

    This is what lets the message list know about attachments without anyone
    having opened the mail, so it has to survive the shapes a real server
    replies in - literals included.
    """

    def _connection(self, response):
        connection = ImapConnection('host', 993, 'ssl', 'user', 'pw')
        connection._uid = lambda *args: ('OK', response)
        return connection

    def test_reports_the_attachment_carrying_message(self):
        connection = self._connection([
            b'1 (UID 10 BODYSTRUCTURE (("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL '
            b'"7BIT" 300 6 NIL NIL NIL NIL)("APPLICATION" "PDF" ("NAME" "invoice.pdf") '
            b'NIL NIL "BASE64" 52000 NIL ("ATTACHMENT" ("FILENAME" "invoice.pdf")) '
            b'NIL NIL) "MIXED" ("BOUNDARY" "y") NIL NIL NIL))',
            b'2 (UID 11 BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL '
            b'"7BIT" 120 4 NIL NIL NIL NIL))',
        ])
        structures = connection.fetch_structures([10, 11])
        self.assertEqual(sorted(structures), [10, 11])
        self.assertEqual(
            [p['filename'] for p in bodystructure.attachments(structures[10])],
            ['invoice.pdf'],
        )
        self.assertEqual(bodystructure.attachments(structures[11]), [])

    def test_asks_for_nothing_when_given_nothing(self):
        connection = ImapConnection('host', 993, 'ssl', 'user', 'pw')
        connection._uid = lambda *args: self.fail("no command should be sent")
        self.assertEqual(connection.fetch_structures([]), {})

    def test_one_unreadable_message_does_not_lose_the_batch(self):
        connection = self._connection([
            b'1 (UID 10 BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL '
            b'"7BIT" 120 4 NIL NIL NIL NIL))',
            b'2 (UID 11 BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" {9}',
            b'3 (UID 12 BODYSTRUCTURE ("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL '
            b'"7BIT" 120 4 NIL NIL NIL NIL))',
        ])
        structures = connection.fetch_structures([10, 11, 12])
        self.assertIn(10, structures)
        self.assertIn(12, structures)

    def test_a_failed_command_is_an_error(self):
        connection = ImapConnection('host', 993, 'ssl', 'user', 'pw')
        connection._uid = lambda *args: ('NO', [b'nope'])
        with self.assertRaises(ImapError):
            connection.fetch_structures([1, 2])


class FakeImap:
    """Just enough of imaplib.IMAP4 to exercise ImapConnection.select()."""

    def __init__(self):
        self.state = 'AUTH'
        self.is_readonly = False
        self.untagged_responses = {'EXISTS': [b'99'], 'UIDVALIDITY': [b'1']}
        self.commands = []

    def _simple_command(self, command, *args):
        self.commands.append((command, args))
        # EXAMINE makes a real server report READ-ONLY.
        self.untagged_responses = {
            'READ-ONLY': [b''],
            'UIDVALIDITY': [b'4242'],
            'UIDNEXT': [b'17'],
            'EXISTS': [b'16'],
        }
        return 'OK', [b'done']

    def response(self, code):
        return code, self.untagged_responses.pop(code, [None])


@tagged('post_install', '-at_install')
class TestSelectBookkeeping(TransactionCase):
    """Regression cover for going around imaplib.select().

    Passing QRESYNC parameters means issuing EXAMINE by hand, which skips the
    bookkeeping imaplib.select() performs. Miss it and the *next* command dies
    with "mailbox status changed to READ-ONLY".
    """

    def _connection(self):
        connection = ImapConnection('host', 993, 'ssl', 'user', 'pw')
        connection.imap = FakeImap()
        return connection

    def test_select_marks_the_session_read_only(self):
        connection = self._connection()
        connection.select('INBOX', readonly=True)
        self.assertTrue(
            connection.imap.is_readonly,
            "EXAMINE reports READ-ONLY; imaplib raises on the next command "
            "unless it knows we asked for a read-only mailbox.",
        )

    def test_select_flushes_stale_untagged_responses(self):
        connection = self._connection()
        connection.imap.untagged_responses['UIDVALIDITY'] = [b'1']
        status = connection.select('INBOX', readonly=True)
        self.assertEqual(
            status['uid_validity'], 4242,
            "Counters from a previously selected folder must not leak through.",
        )
        self.assertEqual(status['uid_next'], 17)

    def test_select_uses_examine_when_read_only(self):
        connection = self._connection()
        connection.select('INBOX', readonly=True)
        self.assertEqual(connection.imap.commands[0][0], 'EXAMINE')
        self.assertEqual(connection.imap.state, 'SELECTED')

    def test_failed_select_leaves_no_mailbox_selected(self):
        connection = self._connection()
        connection.imap._simple_command = lambda *a, **k: ('NO', [b'nope'])
        with self.assertRaises(ImapError):
            connection.select('Missing', readonly=True)
        self.assertEqual(connection.imap.state, 'AUTH')
        self.assertIsNone(connection.selected)


@tagged('post_install', '-at_install')
class TestMessageExtraction(TransactionCase):

    def _headers(self, raw):
        return email.message_from_bytes(raw)

    def test_spam_headers_from_rspamd(self):
        message = self._headers(
            b'X-Spam-Flag: YES\r\nX-Rspamd-Score: 14.20\r\n\r\n'
        )
        result = ImapConnection._parse_spam_headers(message)
        self.assertTrue(result['is_spam'])
        self.assertAlmostEqual(result['spam_score'], 14.20, places=2)

    def test_spam_headers_absent(self):
        result = ImapConnection._parse_spam_headers(self._headers(b'Subject: hi\r\n\r\n'))
        self.assertFalse(result['is_spam'])
        self.assertIsNone(result['spam_score'])

    def test_extract_body_prefers_html_and_flags_attachment(self):
        raw = (
            b'MIME-Version: 1.0\r\n'
            b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
            b'--B\r\nContent-Type: text/plain; charset="utf-8"\r\n\r\nplain version\r\n'
            b'--B\r\nContent-Type: text/html; charset="utf-8"\r\n\r\n<p>rich version</p>\r\n'
            b'--B\r\nContent-Type: application/pdf\r\n'
            b'Content-Disposition: attachment; filename="invoice.pdf"\r\n\r\nPDFDATA\r\n'
            b'--B--\r\n'
        )
        html, text, has_attachment = ImapConnection._extract_body(self._headers(raw))
        self.assertIn('rich version', html)
        self.assertIn('plain version', text)
        self.assertTrue(has_attachment)

    def test_extract_body_broken_charset_does_not_raise(self):
        raw = (
            b'MIME-Version: 1.0\r\n'
            b'Content-Type: text/plain; charset="definitely-not-a-charset"\r\n\r\n'
            b'\xff\xfe broken bytes\r\n'
        )
        html, text, has_attachment = ImapConnection._extract_body(self._headers(raw))
        self.assertEqual(html, '')
        self.assertIn('broken bytes', text)
        self.assertFalse(has_attachment)

    def test_extract_body_inline_image_is_not_an_attachment(self):
        raw = (
            b'MIME-Version: 1.0\r\n'
            b'Content-Type: multipart/related; boundary="B"\r\n\r\n'
            b'--B\r\nContent-Type: text/html\r\n\r\n<p>hi</p>\r\n'
            b'--B\r\nContent-Type: image/png\r\n'
            b'Content-Disposition: inline; filename="logo.png"\r\n\r\nPNG\r\n'
            b'--B--\r\n'
        )
        _html, _text, has_attachment = ImapConnection._extract_body(self._headers(raw))
        self.assertFalse(has_attachment)
