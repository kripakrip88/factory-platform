# -*- coding: utf-8 -*-
"""Окно «Новый лид из письма» (14.10.2026): черновик ничего не создаёт,
поправленное в окне доходит до лида, второй лид на письмо не заводится.

Данные обезличены (example.org); вложений нет — почтовый сервер не нужен.
"""
from datetime import datetime

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadDialog(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env["mail.client.server"].create({
            "name": "Stub", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master"})
        cls.account = cls.env["mail.client.account"].create({
            "name": "Lead", "email": "lead.box@example.org", "server_id": server.id})
        cls.inbox = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": cls.account.id, "imap_path": "INBOX", "role": "inbox"})
        cls.letter = cls.env["mail.client.message"].create({
            "account_id": cls.account.id, "folder_id": cls.inbox.id, "imap_uid": 31,
            "subject": "RE: Заявка на козырьки", "message_id": "<lead-dlg-1@example.org>",
            "email_from": '"Пётр Тестов" <petr@client.example.org>',
            "email_to": "lead.box@example.org", "date": datetime(2026, 10, 14, 1, 30),
            "body_state": "fetched",
            "body_html": "<p>Просим КП на козырьки.</p><p>С уважением,<br/>Пётр Тестов<br/>"
                         "моб. +7 914 000-22-33</p>"})
        cls.company = cls.env["res.partner"].create({"name": "ООО «Клиент-Тест»", "is_company": True})
        cls.Message = cls.env["mail.client.message"]

    def test_draft_shows_what_will_go_and_creates_nothing(self):
        before = self.env["crm.lead"].search_count([])
        draft = self.Message.pmk_lead_draft(self.letter.id)
        self.assertFalse(draft["existing"])
        self.assertEqual(draft["lead"]["name"], "Заявка на козырьки")
        self.assertEqual(draft["lead_sources"]["name"], "тема")
        self.assertEqual(draft["contact"]["contact_name"], "Пётр Тестов")
        self.assertIn("914", draft["contact"]["phone"])
        self.assertEqual(draft["contact"]["email_from"], "petr@client.example.org")
        self.assertFalse(draft["client"])
        self.assertEqual(self.env["crm.lead"].search_count([]), before)

    def test_overrides_reach_the_lead_and_second_lead_is_not_made(self):
        result = self.letter.action_pmk_create_lead({
            "name": "Козырьки, 12 шт.", "partner_id": self.company.id,
            "contact_name": "Пётр", "phone": "+7 914 000-99-99", "email_from": "petr@client.example.org",
            "user_id": 999999,
        })
        self.assertTrue(result["created"])
        lead = self.env["crm.lead"].browse(result["action"]["res_id"])
        self.assertEqual(lead.name, "Козырьки, 12 шт.")
        self.assertEqual(lead.partner_id, self.company)
        self.assertEqual(lead.contact_name, "Пётр")
        self.assertEqual(lead.phone, "+7 914 000-99-99")
        self.assertNotEqual(lead.user_id.id, 999999)
        self.assertEqual(self.letter.pmk_lead_id, lead)
        draft = self.Message.pmk_lead_draft(self.letter.id)
        self.assertEqual(draft["existing"]["id"], lead.id)
        again = self.letter.action_pmk_create_lead({"name": "Ещё один"})
        self.assertFalse(again["created"])
        self.assertEqual(again["action"]["res_id"], lead.id)

    def test_without_overrides_as_before(self):
        result = self.letter.action_pmk_create_lead()
        lead = self.env["crm.lead"].browse(result["action"]["res_id"])
        self.assertEqual(lead.name, "Заявка на козырьки")
        self.assertEqual(lead.email_from, "petr@client.example.org")
