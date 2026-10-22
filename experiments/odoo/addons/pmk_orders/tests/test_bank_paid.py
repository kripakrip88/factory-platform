# -*- coding: utf-8 -*-
"""Оплата счёта Odoo от банка (22.10.2026, этап 5): сделка — «Оплачено / в работе», оплата — в строку."""
from datetime import date

from odoo.tests import tagged

from .test_step_z2_invoice import Z2Common


@tagged("post_install", "-at_install")
class TestBankPaid(Z2Common):

    def test_paid_moves_deal_and_row(self):
        deal = self._deal()
        spec = self._spec(deal, products=[("Секция ограждения ОГ-1", 2, 4500.0)])
        spec.with_user(self.manager).action_pmk_invoice()
        invoice = self._invoices(deal)
        self.assertTrue(invoice._pmk_bank_paid(4000, date(2026, 10, 22), "Модульбанк, п/п 7"))
        self.assertEqual(deal.stage_id, self.env.ref("pmk_deal.stage_in_work"))
        self.assertEqual(invoice.state, "sale", "Счёт подтверждён — заказ в работе.")
        row = deal._pmk_won_row(invoice)
        self.assertEqual((row.pmk_paid_amount, row.pmk_paid_date), (4000, date(2026, 10, 22)))
        invoice._pmk_bank_paid(5000, date(2026, 10, 25), "Модульбанк, п/п 9")
        self.assertEqual(invoice.pmk_bank_paid, 9000)
        self.assertEqual(row.pmk_paid_amount, 9000, "Вторая оплата — к первой.")
        self.assertTrue(any("Оплата по банку" in (m.body or "") for m in invoice.message_ids))

    def test_moysklad_invoice_untouched(self):
        deal = self._deal()
        spec = self._spec(deal, products=[("Секция ограждения ОГ-1", 2, 4500.0)])
        spec.with_user(self.manager).action_pmk_invoice()
        invoice = self._invoices(deal)
        if "pmk_ms_id" not in invoice._fields:
            self.skipTest("pmk_moysklad не установлен")
        invoice.sudo().write({"pmk_ms_id": "ms-bank-1", "pmk_ms_from_odoo": False})  # пришёл из МС
        self.assertFalse(invoice._pmk_bank_paid(4000, date(2026, 10, 22), "Модульбанк"))
        self.assertFalse(invoice.pmk_bank_paid)
        self.assertNotEqual(deal.stage_id, self.env.ref("pmk_deal.stage_in_work"))
