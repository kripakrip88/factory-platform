# -*- coding: utf-8 -*-
"""Лид из письма: клиент по домену и ИНН, телефон из подписи (шаг З-14).

Поиск клиента — общий метод pmk_partner (res.partner._pmk_find_company);
почта зовёт его мягко. Без pmk_partner тесты поиска пропускаются — гонять
вместе:
    odoo -d pmk_mail_test -i pmk_mail_ui,pmk_partner --test-enable \\
         --test-tags /pmk_mail_ui,/pmk_partner --stop-after-init --http-port 8099
Правила подписи без базы — test_signature_rules.py.
"""

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_signature_rules import KYTMANOVA


@tagged("post_install", "-at_install")
class TestZ14LeadClient(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        cls.account = cls.env["mail.client.account"].create({
            "name": "Заявки", "email": "zayavki@pmk-z14.ru", "server_id": cls.server.id,
        })
        cls.folder = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": cls.account.id,
            "imap_path": "INBOX", "role": "inbox",
        })
        cls.uid_seq = 9000
        cls.has_finder = hasattr(cls.env["res.partner"], "_pmk_find_company")
        Partner = cls.env["res.partner"].with_context(no_vat_validation=True)
        cls.branch = Partner.create({
            "name": "ООО ПО «Трубное решение-Тест», филиал Хабаровск",
            "is_company": True, "website": "https://hab.truboproduct-z14.ru/",
            "phone": "+7 (4212) 52-93-57", "active": False,
        })
        cls.inn_company = Partner.create({
            "name": "ООО «ИНН-Тест З14»", "is_company": True, "vat": "7707083893"})

    def setUp(self):
        super().setUp()
        if not self.has_finder:
            self.skipTest("Поиск клиента — в pmk_partner, он не установлен.")

    def _letter(self, email_from, body, subject="Запрос"):
        type(self).uid_seq += 1
        return self.env["mail.client.message"].create({
            "account_id": self.account.id, "folder_id": self.folder.id,
            "imap_uid": self.uid_seq, "subject": subject,
            "email_from": email_from, "date": fields.Datetime.now(),
            "body_html": body, "body_state": "fetched",
            "structure_state": "parsed", "pmk_cid_checked": True,
        })

    def _notes(self, lead):
        return lead.message_ids.filtered(
            lambda m: m.subtype_id == self.env.ref("mail.mt_note"))

    def test_kytmanova(self):
        letter = self._letter("Кытманова Мария <6574@truboproduct-z14.ru>",
                              KYTMANOVA.replace("truboproduct.ru", "truboproduct-z14.ru"),
                              "ПО Трубное решение")
        result = letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertEqual(lead.partner_id, self.branch, "Клиент найден по домену сайта.")
        self.assertEqual(lead.contact_name, "Кытманова Мария")
        self.assertEqual(lead.email_from, "6574@truboproduct-z14.ru")
        self.assertEqual(lead.phone, "+7 (924) 916-84-62", "Телефон из подписи.")
        self.assertEqual(self.branch.phone, "+7 (4212) 52-93-57",
                         "Общий номер филиала не затёрт мобильным.")
        self.assertFalse(self.branch.email, "Личный адрес не ушёл в карточку филиала.")
        self.assertEqual(result["client"], self.branch.display_name)
        note = " ".join(self._notes(lead).mapped("body"))
        self.assertIn("Клиент найден по домену truboproduct-z14.ru", note)
        self.assertIn('data-oe-id="%s"' % self.branch.id, note)
        self.assertIn("в архиве", note)
        self.assertIn("Телефон из подписи: +7 (924) 916-84-62", note)
        # Письмо в ленте — по-прежнему без автора-компании: писал человек.
        posted = lead.message_ids.filtered(lambda m: m.message_type == "email")
        self.assertFalse(posted.author_id)

    def test_public_domain_not_linked(self):
        for domain in ("mail.ru", "gmail.com", "yandex.ru", "bk.ru", "list.ru",
                       "inbox.ru", "rambler.ru", "icloud.com"):
            with self.subTest(domain=domain):
                self.env["res.partner"].create({
                    "name": "ООО «%s»" % domain, "is_company": True,
                    "email": "office@%s" % domain})
                letter = self._letter("client@%s" % domain, "<div>Прошу счёт</div>")
                result = letter.action_pmk_create_lead()
                self.assertFalse(letter.pmk_lead_id.partner_id)
                self.assertFalse(result["client"])

    def test_two_clients_listed_not_guessed(self):
        Partner = self.env["res.partner"]
        first = Partner.create({"name": "ООО «Север-1»", "is_company": True,
                                "email": "a@sever-z14.ru"})
        second = Partner.create({"name": "ООО «Север-2»", "is_company": True,
                                 "website": "sever-z14.ru"})
        letter = self._letter("new@sever-z14.ru", "<div>Запрос</div>")
        letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertFalse(lead.partner_id, "Из двух не угадываем.")
        note = " ".join(self._notes(lead).mapped("body"))
        self.assertIn("подходят несколько клиентов", note)
        self.assertIn('data-oe-id="%s"' % first.id, note)
        self.assertIn('data-oe-id="%s"' % second.id, note)

    def test_inn_in_signature(self):
        letter = self._letter("buh@gmail.com",
                              "<div>Прошу счёт</div><div>ООО «ИНН-Тест»</div>"
                              "<div>ИНН/КПП 7707083893/770701001</div>")
        letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertEqual(lead.partner_id, self.inn_company)
        self.assertIn("по ИНН 7707083893", " ".join(self._notes(lead).mapped("body")))

    def test_exact_address_still_first(self):
        person = self.env["res.partner"].create({
            "name": "Кытманова", "email": "6574@truboproduct-z14.ru",
            "phone": "+7 (924) 000-00-00"})
        letter = self._letter("6574@truboproduct-z14.ru",
                              KYTMANOVA.replace("truboproduct.ru", "truboproduct-z14.ru"))
        self.assertEqual(letter.partner_id, person, "Почтовый модуль нашёл человека.")
        result = letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertEqual(lead.partner_id, person)
        self.assertEqual(lead.phone, "+7 (924) 000-00-00",
                         "Свой телефон человека точнее подписи.")
        self.assertFalse(result["client"], "Точный адрес — не новость.")
        self.assertFalse(self._notes(lead))

    def test_own_mailbox_forward(self):
        letter = self._letter("Коллега <zayavki@pmk-z14.ru>",
                              "<div>Посмотри</div><div>тел. +7 (924) 916-84-62</div>",
                              "Fwd: заявка")
        letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertFalse(lead.phone, "Подпись нашего ящика — не телефон клиента.")
        self.assertFalse(lead.partner_id)

    def test_nothing_found_no_note(self):
        letter = self._letter("x@nobody-z14.ru", "<div>Привет</div>")
        result = letter.action_pmk_create_lead()
        self.assertFalse(letter.pmk_lead_id.partner_id)
        self.assertFalse(self._notes(letter.pmk_lead_id))
        self.assertFalse(result["client"])

    def test_person_on_domain_not_client(self):
        """На домене только человек верхнего уровня (на бою — 92 «Заявка Листы
        гладкие окрашенные», vld12@bvbmail.ru): клиентом не ставится, его
        адрес и телефон не меняются, «Имя контакта» — из письма."""
        person = self.env["res.partner"].create({
            "name": "Заявка Листы З14", "email": "vld12@bvb-z14.ru",
            "phone": "+7 (924) 000-00-01"})
        letter = self._letter("Иван Петров <other@bvb-z14.ru>",
                              "<div>Прошу счёт</div><div>Тел.: +7 (924) 916-84-62</div>")
        result = letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertFalse(lead.partner_id, "Человек по домену клиентом не становится.")
        self.assertFalse(result["client"])
        self.assertEqual(lead.email_from, "other@bvb-z14.ru")
        self.assertEqual(lead.phone, "+7 (924) 916-84-62")
        self.assertEqual(lead.contact_name, "Иван Петров")
        self.assertEqual(person.email, "vld12@bvb-z14.ru", "Карточка человека не тронута.")
        self.assertEqual(person.phone, "+7 (924) 000-00-01")
