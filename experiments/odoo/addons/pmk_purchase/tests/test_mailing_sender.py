# -*- coding: utf-8 -*-
"""Рассылка прайсов — только с zakaz@pmkpark.ru (18.10.2026), независимо от
почты компании: после реквизитов 27.09 письма молча ушли с pmkpark@mail.ru."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailingSender(TransactionCase):

    def test_sender_fixed(self):
        self.env.company.email = "pmkpark@mail.ru"
        tmpl = self.env.ref("pmk_purchase.mail_template_price_request")
        partner = self.env["res.partner"].create({"name": "Поставщик (тест отправителя)",
                                                  "email": "price@example.com"})
        values = tmpl._generate_template([partner.id], ["email_from"])[partner.id]
        self.assertEqual(values["email_from"], "zakaz@pmkpark.ru",
                         "Почта компании на отправителя рассылки не влияет.")
