# -*- coding: utf-8 -*-
"""№306: группа «Все документы» удаляет лиды; «Удалить» сделки — в архив."""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestLeadDelete(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.all_docs = new_test_user(cls.env, "pmk306_all", groups="sales_team.group_sale_salesman_all_leads")
        cls.own = new_test_user(cls.env, "pmk306_own", groups="sales_team.group_sale_salesman")
        cls.partner = cls.env["res.partner"].create({"name": "Клиент (тест №306)", "is_company": True})

    def test_all_documents_delete_leads_archive_deals(self):
        lead = self.env["crm.lead"].create({"name": "Лид (тест №306)", "type": "lead"})
        lead.with_user(self.all_docs).unlink()
        self.assertFalse(lead.exists())
        deal = self.env["crm.lead"].create({"name": "Сделка (тест №306)", "type": "opportunity",
                                            "partner_id": self.partner.id})
        deal.with_user(self.all_docs).unlink()
        self.assertTrue(deal.exists(), "Сделка не удалена…")
        self.assertFalse(deal.active, "…а убрана в архив.")
        self.assertTrue(any("в архив" in (m.body or "") for m in deal.message_ids))
        deal.with_user(self.all_docs).action_unarchive()
        self.assertTrue(deal.active, "И обратно.")

    def test_own_documents_still_cannot(self):
        lead = self.env["crm.lead"].create({"name": "Лид (тест №306)", "type": "lead", "user_id": self.own.id})
        with self.assertRaises(AccessError):
            lead.with_user(self.own).unlink()

    def test_lead_with_invoice_archived(self):
        lead = self.env["crm.lead"].create({"name": "Лид со счётом (тест №306)", "type": "lead",
                                            "partner_id": self.partner.id})
        self.env["sale.order"].create({"partner_id": self.partner.id, "opportunity_id": lead.id})
        lead.with_user(self.all_docs).unlink()
        self.assertTrue(lead.exists())
        self.assertFalse(lead.active)
        lead.unlink()            # администратор (суперпользователь теста) — насовсем
        self.assertFalse(lead.exists())
