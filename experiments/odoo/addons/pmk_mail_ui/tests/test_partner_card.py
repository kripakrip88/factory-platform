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

    def _patched(self, suggest=None):
        """Справочник без сети: по ИНН — отказ, по названию — заданный список."""
        from contextlib import ExitStack
        from odoo.exceptions import UserError
        Partner = type(self.env["res.partner"])
        stack = ExitStack()
        if hasattr(Partner, "_pmk_dadata_find"):
            def no_network(self, inn):
                raise UserError("нет сети в тесте")
            stack.enter_context(patch.object(Partner, "_pmk_dadata_find", no_network))
        if hasattr(Partner, "_pmk_dadata_suggest"):
            stack.enter_context(patch.object(
                Partner, "_pmk_dadata_suggest", lambda self, query, count=5: list(suggest or [])))
        return stack

    def _run(self):
        with self._patched():
            return self.Message.pmk_partner_from_letter(self.letter.id)

    def test_found_with_sources_and_nothing_saved(self):
        before = self.env["res.partner"].search_count([])
        result = self._run()
        self.assertEqual(result["company"]["vat"], self.inn)
        self.assertEqual(result["company_sources"]["vat"], "письмо")
        self.assertEqual(result["contact"]["name"], "Мария Иванова")
        self.assertEqual(result["contact_sources"]["name"], "имя отправителя")
        self.assertEqual(result["contact"]["function"], "Менеджер по закупкам")
        self.assertIn("924", result["contact"]["phone"])
        self.assertEqual(result["contact"]["email"], "maria@newclient.example.org")
        self.assertEqual(self.env["res.partner"].search_count([]), before)

    def test_known_inn_offers_contact_to_existing(self):
        company = self.env["res.partner"].create(
            {"name": "ООО «Новый клиент»", "is_company": True, "vat": self.inn})
        result = self._run()
        self.assertEqual(result["company"]["existing_id"], company.id)
        self.assertEqual(result["contact"]["name"], "Мария Иванова")
        added = self.Message.pmk_partner_create_from_letter(
            self.letter.id, result["company"], result["contact"], {})
        self.assertFalse(added["created"])
        self.assertEqual(added["id"], company.id)
        self.assertEqual(added["contact_added"], "Мария Иванова")
        self.assertEqual(company.child_ids.email, "maria@newclient.example.org")
        again = self.Message.pmk_partner_create_from_letter(
            self.letter.id, result["company"], result["contact"], {})
        self.assertFalse(again["contact_added"])
        self.assertEqual(len(company.child_ids), 1)
        card = self.Message.pmk_partner_card(self.letter.id)
        self.assertEqual(card["partner"]["id"], company.id)

    def test_candidates_already_in_base_are_marked(self):
        inn = _inn10("770000222")
        known = self.env["res.partner"].create(
            {"name": "АО «Известный»", "is_company": True, "vat": inn})
        suggest = [{"inn": inn, "name": {"short_with_opf": "АО «Известный»"},
                    "state": {"status": "ACTIVE"}, "address": {"value": "г Хабаровск"}}]
        with self._patched(suggest):
            if not hasattr(type(self.env["res.partner"]), "_pmk_dadata_suggest"):
                self.skipTest("pmk_dadata не установлен")
            items = self.Message.pmk_partner_suggest("Известный")
        self.assertEqual(items[0]["existing_id"], known.id)

    def test_account_from_attachment(self):
        part = self.env["mail.client.attachment"].create({
            "message_id": self.letter.id, "name": "Карточка.txt", "part_number": "2",
            "content_type": "text/plain"})
        stored = self.env["ir.attachment"].create({
            "name": "Карточка.txt", "raw": "р/с 40702810400000001234\nБИК 040813608".encode()})
        with patch.object(type(part), "_fetch", lambda self: stored):
            result = self._run()
        self.assertEqual(result["bank"]["acc_number"], "40702810400000001234")

    def test_no_inn_name_from_signature_and_candidates(self):
        self.letter.body_html = ("<p>Добрый день.</p><p>Анна Тестова<br/>Ведущий специалист<br/>"
                                 "Альфа-Тест | alfatest.example.org<br/>+7 (800) 000-00-00, доб. 22</p>")
        self.letter.email_from = '"Анна Тестова" <anna@alfatest.example.org>'
        inn = _inn10("770000111")
        suggest = [{"inn": inn, "name": {"short_with_opf": "АО «Альфа-Тест»",
                                         "full_with_opf": "АКЦИОНЕРНОЕ ОБЩЕСТВО «АЛЬФА-ТЕСТ»"},
                    "kpp": "770001001", "state": {"status": "ACTIVE"},
                    "address": {"value": "г Москва", "data": {"city": "Москва"}}}]
        with self._patched(suggest):
            result = self.Message.pmk_partner_from_letter(self.letter.id)
        if not hasattr(type(self.env["res.partner"]), "_pmk_dadata_suggest"):
            self.skipTest("pmk_dadata не установлен")
        self.assertEqual(result["company"]["name"], "Альфа-Тест")
        self.assertEqual(result["company_sources"]["name"], "подпись")
        self.assertEqual(result["query"], "Альфа-Тест")
        self.assertEqual(result["candidates"][0]["vat"], inn)
        self.assertIn("доб. 22", result["contact"]["phone"])

    def test_create_from_window_once(self):
        Message = self.Message
        company = {"name": "ООО «Новый клиент»", "vat": self.inn, "kpp": "270001001", "status": "x"}
        contact = {"name": "Мария Иванова", "phone": "+7 924 000-11-22",
                   "email": "maria@newclient.example.org", "function": "Менеджер"}
        bank = {"acc_number": "40702810400000001234"}
        created = Message.pmk_partner_create_from_letter(self.letter.id, company, contact, bank)
        self.assertTrue(created["created"])
        partner = self.env["res.partner"].browse(created["id"])
        self.assertTrue(partner.is_company)
        self.assertEqual(partner.vat, self.inn)
        self.assertEqual(partner.child_ids.name, "Мария Иванова")
        self.assertEqual(partner.bank_ids.acc_number, "40702810400000001234")
        again = Message.pmk_partner_create_from_letter(self.letter.id, company, contact, bank)
        self.assertFalse(again["created"])
        self.assertEqual(again["id"], partner.id)
