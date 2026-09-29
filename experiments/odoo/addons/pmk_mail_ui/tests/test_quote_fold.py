# -*- coding: utf-8 -*-
"""Свёрнутые цитаты «···» — привязка к окну письма (шаг 20, В2).

Сами правила проверяет test_quote_rules.py (без базы); здесь — та же
таблица через модель (обычные unittest-классы Odoo не запускает) и то, куда
свёртка попадает, а куда нет: окно письма и «Показать картинки» — да, по
разу; лид, цитата ответа, _display_body — нет. И что после пересборки
разметки загрузка из сети заглушена ещё раз (Г13).
"""
import re
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.mail_client_message import _FRAME_HEAD
from .test_quote_rules import CASES, MAILRU_QUOTE

LIVE_LOGOUT = re.compile(r'(?<![\w-])src="/web/session/logout"')
QUOTED = '<div>Добрый день, счёт во вложении.</div>' + MAILRU_QUOTE


@tagged("post_install", "-at_install")
class TestQuoteFold(TransactionCase):

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

    def _message(self, body, subject="Re: Прайс", **values):
        type(self).uid_counter += 1
        return self.Message.create({
            "account_id": self.account.id, "folder_id": self.folder.id,
            "imap_uid": self.uid_counter, "subject": subject,
            "email_from": "client@example.org", "date": fields.Datetime.now(),
            "body_html": body, "body_state": "fetched", "structure_state": "parsed",
            # Картинок из подписи нет — открытие письма в сеть не пойдёт.
            "pmk_cid_checked": True,
            **values,
        })

    def _body(self, message):
        return self.Message.get_message_detail(message.id)["body"]

    # ------------------------------------------------------------------
    def test_rules_table_through_the_model(self):
        for name, body, subject, expected in CASES:
            if not body:
                continue
            with self.subTest(name):
                shown = self._body(self._message(body, subject=subject or "Письмо"))
                self.assertTrue(shown.startswith(_FRAME_HEAD))
                if expected:
                    self.assertEqual(shown.count('<details class="pmk-quote"'), 1)
                    self.assertIn('data-pmk-rule="%s"' % expected, shown)
                else:
                    self.assertNotIn("<details", shown)

    def test_reading_pane_gets_it_once(self):
        shown = self._body(self._message(QUOTED))
        self.assertTrue(shown.startswith(_FRAME_HEAD))
        self.assertEqual(shown.count("<details"), 1)
        self.assertEqual(shown.count("<style>"), 1, "Стили «···» — в том же листе.")
        self.assertIn("details.pmk-quote", _FRAME_HEAD)
        self.assertLess(shown.index("Добрый день, счёт"), shown.index("<details"))

    def test_show_images_folds_once(self):
        message = self._message(QUOTED.replace(
            "cid:logo@x", "https://cdn.example.com/logo.png"))
        before = self._body(message)
        self.assertIn('data-blocked-src="https://cdn.example.com/logo.png"', before)
        after = self.Message.allow_images(message.id)["body"]
        self.assertEqual(after.count("<details"), 1)
        self.assertEqual(after.count("<style>"), 1)
        self.assertIn(' src="https://cdn.example.com/logo.png"', after,
                      "После «Показать картинки» чужая картинка в цитате видна.")

    def test_letter_without_a_quote_is_untouched(self):
        body = "<div>Добрый день</div>"
        shown = self._body(self._message(body))
        self.assertEqual(shown, _FRAME_HEAD + body, "Без свёртки — байт в байт.")

    def test_fold_stays_out_of_lead_quote_and_stored_body(self):
        message = self._message(QUOTED)
        self.assertIn("<details", self._body(message))
        self.assertNotIn("<details", message.body_html)
        for text in (message._display_body(), str(message._quoted_body())):
            self.assertNotIn("<details", text)
            self.assertNotIn("pmk-quote", text)
        message.action_pmk_create_lead()
        letter = message.pmk_lead_id.message_ids.filtered(
            lambda m: m.message_type == "email")
        self.assertTrue(letter)
        self.assertIn("Просим прислать прайс", str(letter.body), "Цитата в лиде целиком.")
        self.assertNotIn("<details", str(letter.body))

    def test_forward_is_not_folded(self):
        shown = self._body(self._message(QUOTED, subject="Fwd: Счёт"))
        self.assertNotIn("<details", shown)

    def test_assets_are_blocked_again_after_rebuild(self):
        """Свёртка пересобирает разметку — после неё глушилка Г13 ещё раз.

        Подменяем первый проход (_display_body отдаёт письмо незаглушённым,
        как если бы строковая проверка что-то пропустила): живой путь к
        нашему серверу не должен выйти из окна письма.
        """
        raw = ('<div>Ответ клиента.</div><div class="mail-quote-collapse"><blockquote>'
               '<span>Пн, 21.09.2026 от a@example.org:</span>'
               '<img src="/web/session/logout"><img src="https://t.example/p.gif">'
               '</blockquote></div>')
        for allowed in (False, True):
            with self.subTest(images_allowed=allowed):
                message = self._message(raw, images_allowed=allowed)
                with patch.object(type(message), "_display_body", lambda self: raw):
                    shown = self._body(message)
                self.assertIn("<details", shown)
                self.assertFalse(LIVE_LOGOUT.search(shown), shown)
                self.assertIn('data-blocked-src="/web/session/logout"', shown)
                if allowed:
                    self.assertIn(' src="https://t.example/p.gif"', shown)
                else:
                    self.assertNotIn(' src="https://t.example/p.gif"', shown)

    def test_word_marks_and_quote_together(self):
        body = ('<div>Ответ.<![if !vml]><img src="cid:a@b"><![endif]></div>'
                + MAILRU_QUOTE)
        shown = self._body(self._message(body))
        self.assertNotIn("[if", shown)
        self.assertEqual(shown.count("<details"), 1)
