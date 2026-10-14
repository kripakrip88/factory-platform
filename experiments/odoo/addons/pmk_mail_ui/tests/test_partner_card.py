# -*- coding: utf-8 -*-
"""Карточка контрагента справа от письма (редизайн почты, шаг 7).

Данные обезличены (example.org). Почтовый сервер не трогаем: у писем текст
уже есть, вложений нет.
"""
from datetime import datetime
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

BOX = "card.box@example.org"


@tagged("post_install", "-at_install")
class TestPartnerCard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env["mail.client.server"].create({
            "name": "Stub", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master"})
        cls.account = cls.env["mail.client.account"].create({
            "name": "Card", "email": BOX, "server_id": server.id})
        Folder = cls.env["mail.client.folder"]
        cls.inbox = Folder.create({"name": "INBOX", "account_id": cls.account.id,
                                   "imap_path": "INBOX", "role": "inbox"})
        cls.sent = Folder.create({"name": "Sent", "account_id": cls.account.id,
                                  "imap_path": "Sent", "role": "sent"})
        cls.company = cls.env["res.partner"].create({
            "name": "ООО «Тестовый завод»", "is_company": True, "vat": "2700000000",
            "city": "Хабаровск", "user_id": cls.env.user.id})
        cls.person = cls.env["res.partner"].create({
            "name": "Иван Тестов", "email": "ivan@client.example.org",
            "parent_id": cls.company.id})
        cls.deal = cls.env["crm.lead"].create({
            "name": "Траверса 10 т", "type": "opportunity", "partner_id": cls.company.id,
            "expected_revenue": 1400000})
        Message = cls.env["mail.client.message"]
        cls.letter = Message.create({
            "account_id": cls.account.id, "folder_id": cls.inbox.id, "imap_uid": 11,
            "subject": "Запрос траверсы", "email_from": '"Иван" <ivan@client.example.org>',
            "email_to": BOX, "message_id": "<card-in@example.org>",
            "date": datetime.now(), "body_html": "<p>Просим КП</p>",
            "body_state": "fetched"})
        cls.ours = Message.create({
            "account_id": cls.account.id, "folder_id": cls.sent.id, "imap_uid": 12,
            "subject": "КП", "email_from": BOX,
            "email_to": '"Иван" <ivan@client.example.org>',
            "message_id": "<card-out@example.org>",
            "date": datetime.now(), "body_html": "<p>КП во вложении</p>",
            "body_state": "fetched"})
        cls.stranger = Message.create({
            "account_id": cls.account.id, "folder_id": cls.inbox.id, "imap_uid": 13,
            "subject": "Привет", "email_from": '"Кто-то" <nobody@unknown.example.org>',
            "email_to": BOX, "message_id": "<card-x@example.org>",
            "date": datetime.now(), "body_html": "<p>Текст</p>",
            "body_state": "fetched"})
        cls.Message = Message

    def test_card_by_sender_address(self):
        card = self.Message.pmk_partner_card(self.letter.id)
        self.assertEqual(card["partner"]["id"], self.company.id)
        self.assertEqual(card["partner"]["vat"], "2700000000")
        self.assertEqual(card["partner"]["manager"], self.env.user.name)
        self.assertEqual(card["deals_total"], 1)
        self.assertEqual(card["deals"][0]["name"], "Траверса 10 т")
        self.assertGreaterEqual(card["letters_year"], 1)

    def test_own_letter_card_is_the_recipient(self):
        card = self.Message.pmk_partner_card(self.ours.id)
        self.assertEqual(card["partner"]["id"], self.company.id)
        self.assertEqual(card["email"], "ivan@client.example.org")

    def test_unknown_sender(self):
        card = self.Message.pmk_partner_card(self.stranger.id)
        self.assertFalse(card["partner"])
        self.assertEqual(card["email"], "nobody@unknown.example.org")
        self.assertEqual(card["sender"], "Кто-то")

    def test_link_to_deal_posts_once(self):
        result = self.Message.pmk_link_lead(self.letter.id, self.deal.id)
        self.assertTrue(result["posted"])
        self.assertEqual(self.letter.pmk_lead_id, self.deal)
        posted = self.env["mail.message"].search([
            ("model", "=", "crm.lead"), ("res_id", "=", self.deal.id),
            ("message_id", "=", "<card-in@example.org>")])
        self.assertEqual(len(posted), 1)
        again = self.Message.pmk_link_lead(self.letter.id, self.deal.id)
        self.assertFalse(again["posted"])
        self.assertEqual(self.env["mail.message"].search_count([
            ("model", "=", "crm.lead"), ("res_id", "=", self.deal.id),
            ("message_id", "=", "<card-in@example.org>")]), 1)
        card = self.Message.pmk_partner_card(self.letter.id)
        self.assertEqual(card["lead"]["id"], self.deal.id)
        self.assertTrue(card["deals"][0]["current"])


def _inn10(body):
    digits = [int(c) for c in body]
    return body + str(sum(d * w for d, w in zip(digits, (2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)


@tagged("post_install", "-at_install")
class TestPartnerFromLetter(TransactionCase):
    """«Создать контрагента» из письма: окно заполнено, база не тронута."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env["mail.client.server"].create({
            "name": "Stub", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master"})
        cls.account = cls.env["mail.client.account"].create({
            "name": "Req", "email": "req.box@example.org", "server_id": server.id})
        cls.inbox = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": cls.account.id, "imap_path": "INBOX", "role": "inbox"})
        cls.inn = _inn10("270000777")
        cls.letter = cls.env["mail.client.message"].create({
            "account_id": cls.account.id, "folder_id": cls.inbox.id, "imap_uid": 21,
            "subject": "Заявка", "email_from": '"Мария Иванова" <maria@newclient.example.org>',
            "email_to": "req.box@example.org", "message_id": "<req-1@example.org>",
            "date": datetime.now(), "body_state": "fetched",
            "body_html": ("<p>Добрый день! Просим счёт.</p><p>С уважением,<br/>"
                          "Менеджер по закупкам<br/>Мария Иванова<br/>"
                          "тел. +7 924 000-11-22<br/>ООО «Новый клиент», ИНН %s</p>" % cls.inn)})
        cls.Message = cls.env["mail.client.message"]

    def _run(self):
        Partner = type(self.env["res.partner"])
        if hasattr(Partner, "_pmk_dadata_find"):
            from odoo.exceptions import UserError

            def no_network(self, inn):
                raise UserError("нет сети в тесте")
            with patch.object(Partner, "_pmk_dadata_find", no_network):
                return self.Message.pmk_partner_from_letter(self.letter.id)
        return self.Message.pmk_partner_from_letter(self.letter.id)

    def test_window_is_filled_and_nothing_saved(self):
        before = self.env["res.partner"].search_count([])
        result = self._run()
        context = result["action"]["context"]
        self.assertEqual(context["default_vat"], self.inn)
        contact = context["default_child_ids"][0][2]
        self.assertEqual(contact["name"], "Мария Иванова")
        self.assertEqual(contact["email"], "maria@newclient.example.org")
        self.assertIn("924", contact["phone"])
        self.assertEqual(contact["function"], "Менеджер по закупкам")
        self.assertTrue(any(self.inn in note for note in result["found"]))
        self.assertEqual(self.env["res.partner"].search_count([]), before)

    def test_known_inn_opens_existing(self):
        company = self.env["res.partner"].create(
            {"name": "ООО «Новый клиент»", "is_company": True, "vat": self.inn})
        result = self._run()
        self.assertEqual(result["action"]["res_id"], company.id)

    def test_account_from_attachment(self):
        part = self.env["mail.client.attachment"].create({
            "message_id": self.letter.id, "name": "Карточка.txt", "part_number": "2",
            "content_type": "text/plain"})
        stored = self.env["ir.attachment"].create({
            "name": "Карточка.txt", "raw": "р/с 40702810400000001234\nБИК 040813608".encode()})
        Part = type(part)
        with patch.object(Part, "_fetch", lambda self: stored):
            result = self._run()
        bank = result["action"]["context"]["default_bank_ids"][0][2]
        self.assertEqual(bank["acc_number"], "40702810400000001234")
