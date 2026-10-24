# -*- coding: utf-8 -*-
"""№306: «Удалить» лиды и сделки у группы «Все документы»; сделку со счётом — нет."""
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestLeadDelete(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.all_docs = new_test_user(cls.env, "pmk306_all", groups="sales_team.group_sale_salesman_all_leads")
        cls.own = new_test_user(cls.env, "pmk306_own", groups="sales_team.group_sale_salesman")
        cls.partner = cls.env["res.partner"].create({"name": "Клиент (тест №306)", "is_company": True})

    def test_all_documents_can_delete(self):
        lead = self.env["crm.lead"].create({"name": "Лид (тест №306)", "type": "lead"})
        deal = self.env["crm.lead"].create({"name": "Сделка (тест №306)", "type": "opportunity",
                                            "partner_id": self.partner.id})
        (lead | deal).with_user(self.all_docs).unlink()
        self.assertFalse((lead | deal).exists())

    def test_own_documents_still_cannot(self):
        lead = self.env["crm.lead"].create({"name": "Лид (тест №306)", "user_id": self.own.id})
        with self.assertRaises(AccessError):
            lead.with_user(self.own).unlink()

    def test_deal_with_invoice_guarded(self):
        deal = self.env["crm.lead"].create({"name": "Сделка со счётом (тест №306)", "type": "opportunity",
                                            "partner_id": self.partner.id})
        self.env["sale.order"].create({"partner_id": self.partner.id, "opportunity_id": deal.id})
        with self.assertRaises(UserError):
            deal.with_user(self.all_docs).unlink()
        self.assertTrue(deal.exists())
        deal.unlink()            # администратор (суперпользователь теста) — может
        self.assertFalse(deal.exists())
