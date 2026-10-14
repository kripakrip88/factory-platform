# -*- coding: utf-8 -*-
"""Ответ и пересылка из Odoo (редизайн почты, шаг 6; доска №40; разбор Г3–Г7).

Письма обезличены: example.org. Почтовый сервер не трогаем — отправка и
скачивание вложений подменены.
"""
import base64
from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

BOX = "reply.box@example.org"


@tagged("post_install", "-at_install")
class TestReplyRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env["mail.client.server"].create({
            "name": "Stub", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master"})
        cls.account = cls.env["mail.client.account"].create({
            "name": "Reply", "email": BOX, "server_id": server.id})
        Folder = cls.env["mail.client.folder"]
        cls.inbox = Folder.create({"name": "INBOX", "account_id": cls.account.id,
                                   "imap_path": "INBOX", "role": "inbox"})
        cls.sent = Folder.create({"name": "Sent", "account_id": cls.account.id,
                                  "imap_path": "Sent", "role": "sent"})
        Message = cls.env["mail.client.message"]
        cls.theirs = Message.create({
            "account_id": cls.account.id, "folder_id": cls.inbox.id, "imap_uid": 1,
            "subject": "Траверса", "email_from": '"Клиент" <client@example.org>',
            "email_to": BOX, "message_id": "<in-1@example.org>",
            "date": datetime(2026, 9, 28, 1, 9), "body_html": "<p>Просим КП</p>",
            "body_state": "fetched"})
        cls.ours = Message.create({
            "account_id": cls.account.id, "folder_id": cls.sent.id, "imap_uid": 2,
            "subject": "RE: Траверса", "email_from": BOX,
            "email_to": '"Клиент" <client@example.org>',
            "email_cc": "boss@example.org, %s" % BOX,
            "message_id": "<out-1@example.org>",
            "date": datetime(2026, 9, 28, 2, 0), "body_html": "<p>КП во вложении</p>",
            "body_state": "fetched"})
        cls.Compose = cls.env["mail.client.compose"]

    # Г3 -------------------------------------------------------------------
    def test_reply_to_client_goes_to_client(self):
        payload = self.Compose.start(self.account.id, "reply", self.theirs.id)
        self.assertIn("client@example.org", payload["email_to"])

    def test_reply_to_own_letter_goes_to_its_recipient(self):
        payload = self.Compose.start(self.account.id, "reply", self.ours.id)
        self.assertIn("client@example.org", payload["email_to"])
        self.assertNotIn(BOX, payload["email_to"])

    def test_reply_all_to_own_letter_keeps_copy_without_ourselves(self):
        payload = self.Compose.start(self.account.id, "reply_all", self.ours.id)
        self.assertIn("client@example.org", payload["email_to"])
        self.assertIn("boss@example.org", payload["email_cc"])
        self.assertNotIn(BOX, payload["email_cc"])

    # Г5 -------------------------------------------------------------------
    def test_quote_header_russian_in_user_timezone(self):
        message = self.theirs.with_context(tz="Asia/Vladivostok")
        header = message._quote_header()
        self.assertTrue(header.startswith("28.09.2026, 11:09, "), header)
        self.assertTrue(header.endswith("пишет:"), header)
        self.assertIn("28.09.2026, 11:09", str(message._quoted_body()))

    # Г4 -------------------------------------------------------------------
    def _sent_from(self, draft):
        sent = []

        def fake_send(self_ims, message, **kwargs):
            sent.append(message)
            return "ok"

        with patch.object(type(self.env["ir.mail_server"]), "send_email", fake_send), \
             patch.object(type(draft), "_append_to_sent", lambda self, msg: True), \
             patch.object(type(draft), "_remove_imap_draft", lambda self: True), \
             patch.object(type(self.account), "_resolve_mail_server",
                          lambda self: self.env["ir.mail_server"].search([], limit=1)
                          or self.env["ir.mail_server"].create(
                              {"name": "s", "smtp_host": "mail.example.org"})), \
             patch.object(type(self.account), "_check_sender_allowed", lambda self, srv: True):
            draft.action_send()
        return sent[0]["From"]

    def _draft(self):
        return self.Compose.create({
            "account_id": self.account.id, "email_to": "client@example.org",
            "subject": "Hi", "body_html": "<p>Hello</p>"})

    def test_sender_name_from_mailbox(self):
        self.account.pmk_sender_name = "ПМК Парк"
        sender = self._sent_from(self._draft())
        self.assertIn("ПМК Парк", sender)
        self.assertIn(BOX, sender)

    def test_sender_name_falls_back_to_user(self):
        self.account.pmk_sender_name = False
        draft = self._draft()
        sender = self._sent_from(draft)
        self.assertIn(draft.user_id.name, sender)
        self.assertIn(BOX, sender)

    # Г6 -------------------------------------------------------------------
    def test_forward_attaches_parts_and_names_the_failed(self):
        Part = self.env["mail.client.attachment"]
        good = Part.create({"message_id": self.theirs.id, "name": "Чертёж.pdf",
                            "part_number": "2", "content_type": "application/pdf"})
        bad = Part.create({"message_id": self.theirs.id, "name": "Смета.xlsx",
                           "part_number": "3"})
        Part.create({"message_id": self.theirs.id, "name": "logo.png",
                     "part_number": "4", "content_type": "image/png", "pmk_inline": True})
        stored = self.env["ir.attachment"].create({
            "name": "Чертёж.pdf", "datas": base64.b64encode(b"%PDF-1.4 test"),
            "mimetype": "application/pdf"})

        def fake_fetch(part):
            if part == bad:
                raise UserError("нет связи")
            if part == good:
                return stored
            raise AssertionError("картинку из текста скачивать не должны")

        with patch.object(type(Part), "_fetch", fake_fetch):
            payload = self.Compose.start(self.account.id, "forward", self.theirs.id)
        self.assertEqual([a["name"] for a in payload["attachments"]], ["Чертёж.pdf"])
        self.assertEqual(payload["pmk_forward_failed"], ["Смета.xlsx"])
        draft = self.Compose.browse(payload["id"])
        self.assertEqual(draft.attachment_ids.raw, b"%PDF-1.4 test")
        self.assertNotEqual(draft.attachment_ids, stored)

    # Г7 -------------------------------------------------------------------
    def test_autosave_does_not_touch_the_mailbox(self):
        draft = self._draft()
        calls = []
        with patch.object(type(draft), "_sync_to_imap_drafts",
                          lambda self: calls.append(self.id) or True):
            self.Compose.save_draft(draft.id, {"subject": "Авто"}, file_on_server=False)
            self.assertEqual(draft.subject, "Авто")
            self.assertEqual(calls, [])
            self.Compose.save_draft(draft.id, {"subject": "Закрыли"})
            self.assertEqual(calls, [draft.id])

    # Подпись пользователя (14.10.2026) ------------------------------------
    def test_user_signature_when_mailbox_has_none(self):
        self.env.user.signature = "<p>С уважением,<br/>Тест Тестов<br/>тел. +7 900 000-00-00</p>"
        payload = self.Compose.start(self.account.id, "new")
        self.assertIn("Тест Тестов", payload["body_html"])
        reply = self.Compose.start(self.account.id, "reply", self.theirs.id)
        body = reply["body_html"]
        self.assertLess(body.index("Тест Тестов"), body.index("blockquote"))

    def test_mailbox_signature_wins_and_reply_skip_is_kept(self):
        self.env.user.signature = "<p>Тест Тестов</p>"
        self.env["mail.client.signature"].create({
            "name": "Общая", "account_id": self.account.id, "is_default": True,
            "use_on_reply": False, "body_html": "<p>Отдел продаж</p>"})
        new = self.Compose.start(self.account.id, "new")["body_html"]
        self.assertIn("Отдел продаж", new)
        self.assertNotIn("Тест Тестов", new)
        reply = self.Compose.start(self.account.id, "reply", self.theirs.id)["body_html"]
        self.assertNotIn("Тест Тестов", reply)
        self.assertNotIn("Отдел продаж", reply)
