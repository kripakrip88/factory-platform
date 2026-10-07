# -*- coding: utf-8 -*-
"""Узел письма на «Связях» — отправитель, а не тема (разбор UX, шаг 27).

Ночной осмотр 29.09, СМ-00024: узлы «Письмо» и «Сделка» показывали одно и то
же «Запрос стоимости изготов…» — лид назван по теме письма. Теперь у письма
первая строка — от кого; тема — в подсказке при наведении.

Шаг 53: щелчок по письму открывает письмо в почте, а если почта его
показать не может (нет окна почты, папка не подписана, ящик чужой) — лид.
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
        # Ящик свой: письмо открывается в почте, только если его папка в
        # дереве почты человека (шаг 53, _pmk_tree_folder_id).
        account = cls.env["mail.client.account"].create({
            "name": "Заявки", "email": "zayavki@example.org", "server_id": server.id,
            "user_id": cls.env.uid,
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

    # ─── Шаг 53: щелчок по письму — письмо в почте, не сделка ───────────
    def test_letter_opens_mail(self):
        """Приёмка 07.10: «Письмо» открывало сделку (лид — та же запись).
        Теперь узел письма несёт окно почты с номером письма."""
        letter = self._letter(4, "Михаил Цыганов <tsyganov@proba-test.ru>")
        nodes = self._nodes()
        node, deal = nodes["mail.client.message"], nodes["crm.lead"]
        action = node["open_action"]
        self.assertTrue(action, "У письма — действие, а не форма записи.")
        self.assertEqual(action["tag"], "mail_client.inbox")
        self.assertEqual(action["params"]["pmk_message_id"], letter.id)
        self.assertTrue(action["params"].get("pmk_crm"), "Почта Продаж: с кнопкой «Лид».")
        self.assertIn("Щелчок — письмо в почте", node["hint"])
        # Действие в базе номером письма не испорчено.
        stored = self.env["ir.actions.actions"]._for_xml_id("pmk_mail_ui.action_mail_sale")
        self.assertNotIn("pmk_message_id", stored.get("params") or {})
        self.assertFalse(deal["open_action"], "Остальные узлы — по-прежнему формой.")

    def test_letter_without_mail_action_falls_back(self):
        """Окна почты нет — клик ведёт по-старому в лид, подсказка это говорит."""
        self._letter(5, "u.pyankova@uess-test.ru")

        def missing(self, full_xml_id):
            raise ValueError(full_xml_id)

        self.patch(type(self.env["ir.actions.actions"]), "_for_xml_id", missing)
        node = self._nodes()["mail.client.message"]
        self.assertFalse(node["open_action"])
        self.assertEqual((node["open_model"], node["open_res_id"]), ("crm.lead", self.lead.id))
        self.assertIn("Щелчок откроет сделку: этого письма нет в вашей почте", node["hint"])

    def test_letter_outside_mail_tree_falls_back(self):
        """Доводка шага 53: папка письма не подписана (перенесли на mail.ru в
        папку, которой в Odoo нет) или ящик чужой — почта открылась бы на
        «Входящих» без письма. Клик ведёт в лид, подсказка это говорит."""
        letter = self._letter(6, "u.pyankova@uess-test.ru")
        hidden = self.env["mail.client.folder"].create({
            "name": "Архив клиентов", "account_id": self.folder.account_id.id,
            "imap_path": "Clients", "role": "other", "subscribed": False,
        })
        letter.folder_id = hidden
        node = self._nodes()["mail.client.message"]
        self.assertFalse(node["open_action"], "Неподписанная папка — не в почту.")
        self.assertEqual((node["open_model"], node["open_res_id"]), ("crm.lead", self.lead.id))
        self.assertIn("Щелчок откроет сделку: этого письма нет в вашей почте", node["hint"])
        # Подписанная папка, но ящик не человека — тоже запасной путь.
        letter.folder_id = self.folder
        self.folder.account_id.user_id = False
        self.assertFalse(self._nodes()["mail.client.message"]["open_action"],
                         "Чужой ящик — не в почту.")
