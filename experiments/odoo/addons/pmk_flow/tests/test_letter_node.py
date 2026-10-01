# -*- coding: utf-8 -*-
"""Узел письма на «Связях» — отправитель, а не тема (разбор UX, шаг 27).

Ночной осмотр 29.09, СМ-00024: узлы «Письмо» и «Сделка» показывали одно и то
же «Запрос стоимости изготов…» — лид назван по теме письма. Теперь у письма
первая строка — от кого; тема — в подсказке при наведении.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLetterNode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        account = cls.env["mail.client.account"].create({
            "name": "Заявки", "email": "zayavki@example.org", "server_id": server.id,
        })
        cls.folder = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": account.id, "imap_path": "INBOX", "role": "inbox",
        })
        cls.subject = "Запрос стоимости изготовления МК п. Горный"
        cls.lead = cls.env["crm.lead"].create({"name": cls.subject, "type": "opportunity"})

    def _letter(self, uid, email_from):
        letter = self.env["mail.client.message"].create({
            "account_id": self.folder.account_id.id, "folder_id": self.folder.id,
            "imap_uid": uid, "subject": self.subject, "email_from": email_from,
            "date": fields.Datetime.now(),
        })
        letter.sudo().pmk_lead_id = self.lead
        return letter

    def _nodes(self):
        graph = self.env["pmk.flow.builder"].get_flow_graph("crm.lead", self.lead.id)
        return {node["model"]: node for node in graph["nodes"]}

    def test_letter_shows_sender_not_subject(self):
        self._letter(1, "Михаил Цыганов <tsyganov@proba-test.ru>")
        nodes = self._nodes()
        letter, deal = nodes["mail.client.message"], nodes["crm.lead"]
        self.assertEqual(letter["label"], "Михаил Цыганов")
        self.assertEqual(deal["label"], self.subject)
        self.assertNotEqual(letter["label"], deal["label"], "Одно название дважды.")
        self.assertIn(self.subject, letter["hint"], "Тема — в подсказке.")
        self.assertTrue(letter["state"].startswith("письмо от "))

    def test_letter_without_name_shows_address(self):
        self._letter(2, "u.pyankova@uess-test.ru")
        self.assertEqual(self._nodes()["mail.client.message"]["label"], "u.pyankova@uess-test.ru")

    def test_letter_name_from_contact_card(self):
        self.env["res.partner"].create({"name": "Пьянкова Ульяна", "email": "u.p@uess-test.ru"})
        letter = self._letter(3, "u.p@uess-test.ru")
        self.assertTrue(letter.partner_id, "Почтовый модуль нашёл контакт по адресу.")
        self.assertEqual(self._nodes()["mail.client.message"]["label"], "Пьянкова Ульяна")
