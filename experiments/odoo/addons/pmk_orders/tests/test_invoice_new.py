# -*- coding: utf-8 -*-
"""«Создать» в списке «Счета покупателям» — окно «Новый счёт» (22.10.2026, этап 5)."""
from lxml import etree

from odoo.tests import tagged

from .test_step_z2_invoice import Z2Common


@tagged("post_install", "-at_install")
class TestInvoiceNew(Z2Common):

    def _wizard(self, **vals):
        return self.env["pmk.invoice.new.wizard"].with_user(self.manager).create(vals)

    def test_deal_with_spec(self):
        deal = self._deal()
        self._spec(deal, products=[("Секция ограждения ОГ-1", 2, 4500.0)])
        wizard = self._wizard(lead_id=deal.id)
        self.assertIn("по расчёту", wizard.hint)
        wizard.action_create()
        invoice = self._invoices(deal)
        self.assertEqual(invoice.order_line.mapped("name"), ["Секция ограждения ОГ-1"])
        # Второй раз — тот же счёт, второй не заводим.
        self.assertIn("уже есть счёт", self._wizard(lead_id=deal.id).hint)
        self._wizard(lead_id=deal.id).action_create()
        self.assertEqual(len(self._invoices(deal)), 1)

    def test_client_only_blank(self):
        client = self.env["res.partner"].create({"name": "ООО «Услуги»", "is_company": True})
        wizard = self._wizard(partner_id=client.id)
        self.assertIn("Заведём сделку", wizard.hint)
        wizard.action_create()
        deal = self.env["crm.lead"].search([("partner_id", "=", client.id)])
        self.assertEqual(len(deal), 1)
        invoice = self._invoices(deal)
        self.assertEqual(invoice.order_line.mapped("name"), ["Изделие"], "Пустой черновик — строка «Изделие».")
        self.assertFalse(invoice.pmk_spec_id)

    def test_list_button(self):
        arch = etree.fromstring(self.env["sale.order"].get_views([(False, "list")])["views"]["list"]["arch"])
        buttons = arch.xpath("//header/button[@string='Создать']")
        self.assertTrue(buttons)
        self.assertEqual(buttons[0].get("display"), "always")
