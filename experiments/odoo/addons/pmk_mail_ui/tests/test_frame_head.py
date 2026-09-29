# -*- coding: utf-8 -*-
"""Лист письма в окне чтения (разбор UX, Г2).

Заголовок (<base target=_blank>, шрифт, отступы Word) ложится на КАЖДОЕ
открытие письма — и на рано выходящий путь без картинок из подписи, и на
«Показать картинки», — ровно один раз, и никуда больше: ни в лид, ни в
цитату ответа.
"""
import base64

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.mail_client_message import _FRAME_HEAD

# Картинка 1×1 PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


@tagged("post_install", "-at_install")
class TestFrameHead(TransactionCase):

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
        type(self).uid_counter += 1
        return self.Message.create({
            "account_id": self.account.id, "folder_id": self.folder.id,
            "imap_uid": self.uid_counter, "subject": "Письмо",
            "email_from": "client@example.org", "date": fields.Datetime.now(),
            "body_html": body, "body_state": "fetched",
            # Уже разобрано — открытие письма не пойдёт в сеть.
            "structure_state": "parsed",
            **values,
        })

    def _with_logo(self, body):
        message = self._message(body, pmk_cid_checked=True)
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
        return message

    # ------------------------------------------------------------------
    def test_plain_letter_gets_the_sheet(self):
        message = self._message("<div>Добрый день</div>")
        body = self.Message.get_message_detail(message.id)["body"]
        self.assertTrue(body.startswith(_FRAME_HEAD))
        self.assertTrue(body.endswith("<div>Добрый день</div>"))

    def test_letter_with_signature_picture_gets_the_sheet_too(self):
        message = self._with_logo('<p>Подпись</p><img src="cid:logo@x">')
        detail = self.Message.get_message_detail(message.id)
        self.assertTrue(detail["body"].startswith(_FRAME_HEAD))
        self.assertIn('src="data:image/png;base64,', detail["body"])
        self.assertEqual(detail["attachments"], [], "Логотип — в тексте, не в списке.")

    def test_markup_body_is_not_escaped(self):
        # Картинки разрешены, вырезать нечего: модуль почты отдаёт Markup.
        message = self._message("<p>Привет</p>", images_allowed=True)
        body = self.Message.get_message_detail(message.id)["body"]
        self.assertNotIn("&lt;base", body)
        self.assertEqual(body.count("<base"), 1)
        self.assertIn("<p>Привет</p>", body)

    def test_show_images_adds_it_once(self):
        message = self._message('<img src="https://cdn.example.com/a.png">')
        body = self.Message.allow_images(message.id)["body"]
        self.assertEqual(body.count("<base"), 1)
        self.assertEqual(body.count("<style>"), 1)
        self.assertIn(' src="https://cdn.example.com/a.png"', body)

    def test_empty_and_failed_bodies_stay_empty(self):
        message = self._message("", body_state="failed")
        self.assertEqual(self.Message.get_message_detail(message.id)["body"], "")

    def test_sheet_stays_out_of_lead_and_quote(self):
        message = self._message("<p>Заявка на ограждения</p>")
        for text in (message._display_body(), str(message._quoted_body())):
            self.assertNotIn("<base", text)
            self.assertNotIn("<style", text)

        message.action_pmk_create_lead()
        letter = message.pmk_lead_id.message_ids.filtered(
            lambda m: m.message_type == "email")
        self.assertTrue(letter)
        self.assertIn("Заявка на ограждения", str(letter.body))
        self.assertNotIn("<base", str(letter.body))
        self.assertNotIn("<style", str(letter.body))
