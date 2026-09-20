# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Remote asset blocking.

A single request that escapes the block tells the sender the message was
opened, which is the whole thing this is meant to prevent. Newsletters reach
for images in several ways, so every one of them is covered here.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRemoteAssetBlocking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Message = cls.env['mail.client.message']
        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
        })
        cls.account = cls.env['mail.client.account'].create({
            'name': 'Test', 'email': 'test@example.org', 'server_id': cls.server.id,
        })
        cls.folder = cls.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': cls.account.id,
            'imap_path': 'INBOX', 'role': 'inbox',
        })

    def _message(self, body):
        return self.Message.create({
            'account_id': self.account.id, 'folder_id': self.folder.id,
            'imap_uid': 1, 'subject': 'Newsletter',
            'body_html': body, 'body_state': 'fetched',
            # Already inspected, so reading it never reaches for the network.
            'structure_state': 'parsed',
        })

    def _rendered(self, body):
        return self._message(body)._display_body()

    # ------------------------------------------------------------------
    def test_img_src_is_blocked(self):
        rendered = self._rendered('<img src="https://tracker.example.com/pixel.gif"/>')
        self.assertIn('data-blocked-src', rendered)
        self.assertNotIn('<img src="https', rendered)

    def test_css_background_image_is_blocked(self):
        """The gap real newsletters actually use."""
        rendered = self._rendered(
            '<div style="background-image:url(https://cdn.example.com/banner.jpg)">x</div>'
        )
        self.assertIn('url(about:blank)', rendered)
        self.assertNotIn('cdn.example.com', rendered)

    def test_css_url_with_quotes_is_blocked(self):
        rendered = self._rendered(
            "<td style=\"background:url('https://cdn.example.com/bg.png') repeat\">x</td>"
        )
        self.assertNotIn('cdn.example.com', rendered)

    def test_srcset_is_blocked(self):
        rendered = self._rendered(
            '<img srcset="https://cdn.example.com/a.png 1x" src="https://cdn.example.com/a.png"/>'
        )
        self.assertIn('data-blocked-srcset', rendered)
        self.assertIn('data-blocked-src', rendered)
        self.assertNotIn(' src="https', rendered)
        self.assertNotIn(' srcset="https', rendered)

    def test_every_remote_attribute_in_a_tag_is_blocked(self):
        """Regression: only the first attribute per tag used to be caught."""
        rendered = self._rendered(
            '<td background="https://cdn.example.com/bg.gif">'
            '<img srcset="https://cdn.example.com/a.png 2x" '
            'src="https://cdn.example.com/a.png" '
            'poster="https://cdn.example.com/p.jpg"/></td>'
        )
        for attribute in ('background', 'srcset', 'src', 'poster'):
            self.assertIn('data-blocked-%s=' % attribute, rendered)
        self.assertNotIn(
            ' src="https', rendered,
            "A single unblocked attribute is enough to confirm the open.",
        )

    def test_background_attribute_is_blocked(self):
        rendered = self._rendered('<table background="https://cdn.example.com/bg.gif"><tr/></table>')
        self.assertIn('data-blocked-background', rendered)

    def test_embedded_and_relative_images_are_left_alone(self):
        """cid: and data: images are part of the message, not a network call."""
        body = (
            '<img src="cid:logo@example.org"/>'
            '<img src="data:image/png;base64,AAAA"/>'
        )
        rendered = self._rendered(body)
        self.assertNotIn('data-blocked-src', rendered)
        self.assertIn('cid:logo@example.org', rendered)

    def test_allowing_images_restores_the_original(self):
        message = self._message(
            '<div style="background-image:url(https://cdn.example.com/b.jpg)">'
            '<img src="https://cdn.example.com/a.png"/></div>'
        )
        blocked = message._display_body()
        # The URL survives inside the renamed attribute on purpose - what
        # matters is that nothing fetchable points at it.
        self.assertIn('data-blocked-src="https://cdn.example.com/a.png"', blocked)
        self.assertNotIn('<img src="https', blocked)
        self.assertIn('url(about:blank)', blocked)

        message.images_allowed = True
        rendered = message._display_body()
        self.assertIn('https://cdn.example.com/a.png', rendered)
        self.assertIn(
            'url(https://cdn.example.com/b.jpg)', rendered,
            "Blocking must not damage the stored body.",
        )

    def test_detection_reports_css_only_images(self):
        message = self._message(
            '<div style="background-image:url(https://cdn.example.com/b.jpg)">x</div>'
        )
        detail = self.Message.get_message_detail(message.id)
        self.assertTrue(
            detail['has_blocked_images'],
            "The banner must appear even when the only images come from CSS.",
        )

    def test_no_banner_when_there_is_nothing_remote(self):
        message = self._message('<p>Plain text only</p>')
        detail = self.Message.get_message_detail(message.id)
        self.assertFalse(detail['has_blocked_images'])
