# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""BODYSTRUCTURE parsing.

Getting the part numbers right is what lets the client fetch a two-line reply
out of a message carrying a 20 MB attachment. Getting them wrong means either
downloading everything or handing the user the wrong file.
"""
from odoo.tests import TransactionCase, tagged

from ..tools import bodystructure

SIMPLE_TEXT = (
    b'("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 120 4 NIL NIL NIL NIL)'
)

ALTERNATIVE = (
    b'(("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "QUOTED-PRINTABLE" 200 6 NIL NIL NIL NIL)'
    b'("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "QUOTED-PRINTABLE" 400 8 NIL NIL NIL NIL)'
    b'"ALTERNATIVE" ("BOUNDARY" "x") NIL NIL NIL)'
)

MIXED_WITH_PDF = (
    b'(("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "7BIT" 300 6 NIL NIL NIL NIL)'
    b'("APPLICATION" "PDF" ("NAME" "invoice.pdf") NIL NIL "BASE64" 52000 NIL '
    b'("ATTACHMENT" ("FILENAME" "invoice.pdf")) NIL NIL)'
    b'"MIXED" ("BOUNDARY" "y") NIL NIL NIL)'
)

NESTED = (
    b'((("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 100 3 NIL NIL NIL NIL)'
    b'("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "7BIT" 200 4 NIL NIL NIL NIL)'
    b'"ALTERNATIVE" ("BOUNDARY" "inner") NIL NIL NIL)'
    b'("IMAGE" "PNG" ("NAME" "logo.png") NIL NIL "BASE64" 9000 NIL '
    b'("ATTACHMENT" ("FILENAME" "logo.png")) NIL NIL)'
    b'"MIXED" ("BOUNDARY" "outer") NIL NIL NIL)'
)


@tagged('post_install', '-at_install')
class TestBodyStructure(TransactionCase):

    def test_single_text_part(self):
        parts = bodystructure.parse_parts(SIMPLE_TEXT)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]['part_number'], '1')
        self.assertEqual(parts[0]['content_type'], 'text/plain')
        self.assertEqual(parts[0]['charset'], 'utf-8')
        self.assertFalse(parts[0]['is_attachment'])

    def test_alternative_numbers_parts_in_order(self):
        parts = bodystructure.parse_parts(ALTERNATIVE)
        self.assertEqual([p['part_number'] for p in parts], ['1', '2'])
        html, text = bodystructure.pick_body_parts(parts)
        self.assertEqual(html['part_number'], '2')
        self.assertEqual(text['part_number'], '1')
        self.assertEqual(html['encoding'], 'quoted-printable')

    def test_attachment_is_detected_with_its_part_number(self):
        parts = bodystructure.parse_parts(MIXED_WITH_PDF)
        attachments = bodystructure.attachments(parts)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]['filename'], 'invoice.pdf')
        self.assertEqual(
            attachments[0]['part_number'], '2',
            "Fetching the wrong part number hands the user the wrong file.",
        )
        self.assertEqual(attachments[0]['size'], 52000)
        self.assertEqual(attachments[0]['encoding'], 'base64')

    def test_body_parts_exclude_attachments(self):
        parts = bodystructure.parse_parts(MIXED_WITH_PDF)
        html, text = bodystructure.pick_body_parts(parts)
        self.assertEqual(html['part_number'], '1')
        self.assertIsNone(text)

    def test_nested_multipart_numbering(self):
        parts = bodystructure.parse_parts(NESTED)
        numbers = {p['content_type']: p['part_number'] for p in parts}
        self.assertEqual(numbers['text/plain'], '1.1')
        self.assertEqual(numbers['text/html'], '1.2')
        self.assertEqual(numbers['image/png'], '2')

    def test_quoted_string_escapes(self):
        raw = (
            b'("APPLICATION" "PDF" ("NAME" "quarter \\"final\\".pdf") NIL NIL "BASE64" 10 NIL '
            b'("ATTACHMENT" ("FILENAME" "quarter \\"final\\".pdf")) NIL NIL)'
        )
        parts = bodystructure.parse_parts(raw)
        self.assertEqual(parts[0]['filename'], 'quarter "final".pdf')

    def test_rfc2047_filename_is_decoded(self):
        raw = (
            b'("APPLICATION" "PDF" ("NAME" "=?utf-8?B?bGFwb3Jhbi5wZGY=?=") NIL NIL "BASE64" 10 NIL '
            b'("ATTACHMENT" ("FILENAME" "=?utf-8?B?bGFwb3Jhbi5wZGY=?=")) NIL NIL)'
        )
        parts = bodystructure.parse_parts(raw)
        self.assertEqual(parts[0]['filename'], 'laporan.pdf')

    def test_inline_image_is_not_an_attachment(self):
        raw = (
            b'(("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "7BIT" 100 2 NIL NIL NIL NIL)'
            b'("IMAGE" "PNG" ("NAME" "sig.png") "<sig@x>" NIL "BASE64" 900 NIL '
            b'("INLINE" ("FILENAME" "sig.png")) NIL NIL)'
            b'"RELATED" ("BOUNDARY" "z") NIL NIL NIL)'
        )
        parts = bodystructure.parse_parts(raw)
        image = [p for p in parts if p['content_type'] == 'image/png'][0]
        self.assertFalse(
            image['is_attachment'],
            "A signature logo shown inside the body is not an attachment.",
        )

    def test_inline_without_content_id_is_an_attachment(self):
        """Outlook marks ordinary attachments as inline; users still expect them."""
        raw = (
            b'(("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "7BIT" 100 2 NIL NIL NIL NIL)'
            b'("APPLICATION" "PDF" ("NAME" "po.pdf") NIL NIL "BASE64" 900 NIL '
            b'("INLINE" ("FILENAME" "po.pdf")) NIL NIL)'
            b'"MIXED" ("BOUNDARY" "z") NIL NIL NIL)'
        )
        parts = bodystructure.parse_parts(raw)
        pdf = [p for p in parts if p['content_type'] == 'application/pdf'][0]
        self.assertTrue(pdf['is_attachment'])

    def test_literal_syntax_is_supported(self):
        raw = b'("TEXT" "PLAIN" ("CHARSET" {5}\r\nutf-8) NIL NIL "7BIT" 10 1 NIL NIL NIL NIL)'
        parts = bodystructure.parse_parts(raw)
        self.assertEqual(parts[0]['charset'], 'utf-8')

    def test_malformed_input_raises_cleanly(self):
        with self.assertRaises(bodystructure.BodyStructureError):
            bodystructure.parse_parts(b'not a structure at all')

    # ------------------------------------------------------------------
    # truncated and malformed literals
    #
    # A response can be cut short by a dropped connection or a server bug. The
    # tokenizer used to spin for ever on one shape of that - past the end of
    # the buffer the slice is b'', and `b'' in b'\r\n'` is True, so the loop
    # skipping CRLF after "{9}" never advanced. It hung the sync worker on a
    # pegged core rather than failing the folder and moving on.
    # ------------------------------------------------------------------
    def test_literal_cut_off_at_the_end_does_not_hang(self):
        with self.assertRaises(bodystructure.BodyStructureError):
            bodystructure.parse_parts(b'("TEXT" "PLAIN" ("CHARSET" {9}')

    def test_literal_longer_than_what_is_left_does_not_hang(self):
        with self.assertRaises(bodystructure.BodyStructureError):
            bodystructure.parse_parts(b'("TEXT" "PLAIN" ("CHARSET" {99}\r\nutf-8)')

    def test_literal_with_an_unreadable_length(self):
        with self.assertRaises(bodystructure.BodyStructureError):
            bodystructure.parse_parts(b'("TEXT" "PLAIN" {abc}\r\nxx)')

    def test_literal_with_no_closing_brace(self):
        with self.assertRaises(bodystructure.BodyStructureError):
            bodystructure.parse_parts(b'("TEXT" "PLAIN" {9')

    def test_a_literal_at_the_very_end_still_parses(self):
        """The bound must not break the case it was added to protect."""
        raw = b'("TEXT" "PLAIN" ("CHARSET" {5}\r\nutf-8'
        self.assertEqual(bodystructure.parse_parts(raw)[0]['charset'], 'utf-8')
