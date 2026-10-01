# -*- coding: utf-8 -*-
"""Кнопка «Лид» ставит «Откуда пришёл = Почта» (разбор UX, шаг 31).

Поле объявлено в pmk_deal; почта от модуля сделки не зависит. Без pmk_deal
тест пропускается, а лид создаётся как раньше.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadSource(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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

    def test_lead_from_letter_is_marked_mail(self):
        if "pmk_source" not in self.env["crm.lead"]._fields:
            self.skipTest("pmk_deal не установлен — поля «Откуда пришёл» нет")
        message = self.env["mail.client.message"].create({
            "account_id": self.account.id, "folder_id": self.folder.id,
            "imap_uid": 1, "subject": "Запрос КП на каркас",
            "email_from": "client@example.org", "date": fields.Datetime.now(),
            "body_html": "<div>Прошу посчитать</div>", "body_state": "fetched",
            "structure_state": "parsed", "pmk_cid_checked": True,
        })
        message.action_pmk_create_lead()
        self.assertEqual(message.pmk_lead_id.pmk_source, "mail")

    def test_lead_received_is_letter_date(self):
        """«Получен» — дата письма, а не момент нажатия «Лид» (шаг 25)."""
        if "pmk_received" not in self.env["crm.lead"]._fields:
            self.skipTest("pmk_deal не установлен — поля «Получен» нет")
        letter_date = fields.Datetime.now() - timedelta(days=4)
        message = self.env["mail.client.message"].create({
            "account_id": self.account.id, "folder_id": self.folder.id,
            "imap_uid": 2, "subject": "Запрос КП на ферму",
            "email_from": "client@example.org", "date": letter_date,
            "body_html": "<div>Прошу посчитать</div>", "body_state": "fetched",
            "structure_state": "parsed", "pmk_cid_checked": True,
        })
        message.action_pmk_create_lead()
        lead = message.pmk_lead_id
        self.assertEqual(lead.pmk_received, message.date)
        self.assertLess(lead.pmk_received, lead.create_date)
