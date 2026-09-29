# -*- coding: utf-8 -*-
"""Картинки по адресу без «http» — привязка к модулю почты (разбор UX, Г13).

Сами правила проверяет test_asset_rules.py (без базы). Здесь — что они
стоят во всех местах, где письмо показывается или цитируется:
окно письма до и после «Показать картинки», плашка, метки Word, картинки
из подписи, чат лида, цитата ответа.
"""
import base64
import re

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_asset_rules import CASES

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

# Живой (не заглушённый) атрибут src с этим адресом.
LIVE_LOGOUT = re.compile(r'(?<![\w-])src="/web/session/logout"')


@tagged("post_install", "-at_install")
class TestRemotePaths(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].set_param("web.base.url", "https://erppark.ru")
        cls.Message = cls.env["mail.client.message"]
        cls.server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        cls.account = cls.env["mail.client.account"].create({
            "name": "Test", "email": "test@example.org", "server_id": cls.server.id,
        })
        cls.folder = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": cls.account.id,
            "imap_path": "INBOX", "role": "inbox",
        })
        cls.uid_counter = 0

    def _message(self, body, **values):
        # imap_uid у каждого свой: иначе UNIQUE(folder_id, imap_uid).
        type(self).uid_counter += 1
        return self.Message.create({
            "account_id": self.account.id, "folder_id": self.folder.id,
            "imap_uid": self.uid_counter, "subject": "Письмо",
            "email_from": "client@example.org", "date": fields.Datetime.now(),
            "body_html": body, "body_state": "fetched", "structure_state": "parsed",
            **values,
        })

    def _detail(self, message):
        return self.Message.get_message_detail(message.id)

    # ------------------------------------------------------------------
    # окно письма
    # ------------------------------------------------------------------
    def test_rules_table_through_the_model(self):
        """Таблица test_asset_rules.py — здесь, через модель: сам Odoo обычные
        unittest-классы не запускает. Имя нашего сервера — из web.base.url."""
        for body, when_blocked, when_allowed in CASES:
            for allow, expected in ((False, when_blocked), (True, when_allowed)):
                with self.subTest(body=body, allow=allow):
                    out = self.Message._pmk_block_assets(body, allow_remote=allow)
                    self.assertEqual("kept" if out == body else "blocked", expected, out)
                    self.assertEqual(self.Message._pmk_block_assets(out, allow_remote=allow), out)

    def test_before_and_after_show_images(self):
        # (текст, остаётся живым до кнопки, остаётся живым после кнопки)
        cases = [
            ('<img src="//tracker.example/p.gif">', False, True),
            ('<img src="HTTPS://t.example/p.gif">', False, True),
            ('<img src="https://erppark.ru/web/image/5?access_token=x">', False, True),
            ('<img src="/web/session/logout">', False, False),
            ('<img src="https://erppark.ru/web/session/logout">', False, False),
            ('<img src="//www.erppark.ru/web/session/logout">', False, False),
            ('<img src="cid:image001.png@01DD">', True, True),
            ('<img src="data:image/png;base64,AAAA">', True, True),
        ]
        for body, live_before, live_after in cases:
            with self.subTest(body=body):
                message = self._message(body)
                self.assertEqual(message._display_body() == body, live_before)
                message.images_allowed = True
                self.assertEqual(message._display_body() == body, live_after)

    def test_blocking_twice_changes_nothing(self):
        body = ('<img src="//t.example/p.gif"><img src="/web/session/logout">'
                '<div style="background:url(/x.png)">x</div>'
                '<img src="https://cdn.example.com/a.png">')
        once = self.Message._block_remote_assets(body)
        self.assertEqual(self.Message._block_remote_assets(once), once)
        self.assertNotIn("data-blocked-data-blocked", once)
        self.assertNotIn(' src="', once.replace('data-blocked-src="', ""))

    def test_banner_only_when_the_button_can_help(self):
        cases = [
            ('<img src="//t.example/p.gif">', True),
            ('<div style="background:url(&quot;//t.example/q.png&quot;)">x</div>', True),
            ('<img src="https://erppark.ru/web/image/5?access_token=x">', True),
            ('<img src="/web/session/logout">', False),
            ('<img src="https://erppark.ru/web/session/logout">', False),
            ('<img src="cid:logo@x"><img src="data:image/png;base64,AAAA">', False),
            ("<p>Просто текст</p>", False),
        ]
        for body, banner in cases:
            with self.subTest(body=body):
                detail = self._detail(self._message(body))
                self.assertEqual(detail["has_blocked_images"], banner)

    def test_show_images_keeps_our_server_blocked(self):
        message = self._message(
            '<img src="//t.example/p.gif">'
            '<img src="/web/session/logout">'
            '<img src="https://erppark.ru/web/session/logout">'
            '<div style="background:url(/x.png)">x</div>')
        body = self.Message.allow_images(message.id)["body"]
        self.assertIn(' src="//t.example/p.gif"', body)
        self.assertIn('data-blocked-src="/web/session/logout"', body)
        self.assertIn('data-blocked-src="https://erppark.ru/web/session/logout"', body)
        self.assertIn("url(about:blank)", body)
        self.assertIsNone(LIVE_LOGOUT.search(body))

    def test_word_conditionals(self):
        # Так метки Word записывает санитайзер.
        message = self._message(
            '&lt;![if !vml]&gt;<img src="//t.example/p.gif">&lt;![endif]&gt;')
        body = message._display_body()
        self.assertNotIn("[if", body)
        self.assertNotIn("[endif]", body)
        self.assertEqual(body.count("data-blocked-src"), 1)
        message.images_allowed = True
        self.assertIn(' src="//t.example/p.gif"', message._display_body())

    def test_signature_picture_survives_next_to_a_blocked_path(self):
        message = self._message(
            '<img src="cid:logo@x"><img src="/web/session/logout">', pmk_cid_checked=True)
        attachment = self.env["ir.attachment"].create({
            "name": "logo.png", "raw": PNG,
            "res_model": "mail.client.message", "res_id": message.id,
        })
        self.env["mail.client.attachment"].create({
            "message_id": message.id, "name": "logo.png", "part_number": "2",
            "content_type": "image/png", "encoding": "base64", "file_size": len(PNG),
            "state": "fetched", "attachment_id": attachment.id,
            "pmk_content_id": "logo@x", "pmk_inline": True,
        })
        body = self._detail(message)["body"]
        self.assertIn('src="data:image/png;base64,', body)
        self.assertIn('data-blocked-src="/web/session/logout"', body)
        self.assertIsNone(LIVE_LOGOUT.search(body))

    # ------------------------------------------------------------------
    # лид и цитата — письмо прямо на странице Odoo, с сессией
    # ------------------------------------------------------------------
    def test_lead_gets_no_path_to_our_server(self):
        message = self._message(
            '<p>Заявка</p><img src="cid:logo@x"><img src="/web/session/logout">'
            '<div style="background-image:url(/x)">y</div>', pmk_cid_checked=True)
        attachment = self.env["ir.attachment"].create({
            "name": "logo.png", "raw": PNG,
            "res_model": "mail.client.message", "res_id": message.id,
        })
        self.env["mail.client.attachment"].create({
            "message_id": message.id, "name": "logo.png", "part_number": "2",
            "content_type": "image/png", "encoding": "base64", "file_size": len(PNG),
            "state": "fetched", "attachment_id": attachment.id,
            "pmk_content_id": "logo@x", "pmk_inline": True,
        })
        message.action_pmk_create_lead()
        letter = message.pmk_lead_id.message_ids.filtered(
            lambda m: m.message_type == "email")
        body = str(letter.body)
        # Ссылку cid: ядро заменяет на свою картинку с токеном — она цела.
        self.assertIn("/web/image/", body)
        self.assertIn("access_token=", body)
        self.assertIsNone(LIVE_LOGOUT.search(body))
        self.assertNotIn("url(/x", body)

    def test_quote_blocks_paths_but_keeps_remote_pictures(self):
        message = self._message(
            '<img src="/web/session/logout"><img src="https://cdn.example.com/a.png">')
        quoted = str(message._quoted_body())
        self.assertIn('data-blocked-src="/web/session/logout"', quoted)
        self.assertIn(' src="https://cdn.example.com/a.png"', quoted,
                      "Цитата уходит адресату — чужие картинки, как у вендора.")

        draft = self.env["mail.client.compose"].start(self.account.id, "reply", message.id)
        self.assertIsNone(LIVE_LOGOUT.search(draft["body_html"]))
