# -*- coding: utf-8 -*-
"""Цены ВСЕГДА с НДС (решение Антона 08.10.2026, шаг З-2), pmk_orders.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные.

«Если будет справочник типовых изделий с ценой 150 ₽: от ИП Чулкова
выставляется 150 ₽ в т. ч. НДС 22%, а от ООО на УСН — тоже 150 ₽, но в счёте
„Без НДС“» — не 122,95. Компания Odoo — «цены включают налог»
(pmk_org.hooks.ensure_company_price_included), налог строки ставит режим
организации на дату, цену строки никто не пересчитывает.

Что ловим:
  • компания в режиме «цены включают налог», налоги режимов следуют ей;
  • товар-услуга 150 ₽ с налогом товара «НДС 22%» (как 753 товара на боевой):
    от организации на НДС 22% — строка 150, итог 150, налог 27,05, без
    налога 122,95; от организации на УСН — строка 150, итог 150, налог 0;
  • смена организации в черновике (и в форме, как менеджер в браузере) —
    налог сменился, цена 150 осталась;
  • КП и счёт из расчёта сходятся: итог, «в том числе НДС» печати КП =
    налогу счёта; на УСН — «Без НДС (УСН)» и налог 0.
"""
from odoo import Command
from odoo.tests import Form, tagged

from .test_step_z2_invoice import Z2Common


@tagged("post_install", "-at_install")
class TestStepZ2Prices(Z2Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Типовое изделие справочника: услуга, 150 ₽, налог товара — «НДС
        # 22%» (как налог 7 у всех товаров на боевой).
        cls.typical = cls.env["product.product"].create({
            "name": "Кронштейн типовой (шаг З-2)",
            "type": "service",
            "list_price": 150.0,
            "taxes_id": [Command.set(cls.taxes["vat22"].ids)],
        })

    def _order(self, org, user=None):
        Order = self.env["sale.order"].with_user(user or self.manager)
        return Order.create({
            "partner_id": self.client.id,
            "pmk_org_id": org.id,
            "order_line": [Command.create({"product_id": self.typical.id, "product_uom_qty": 1})],
        })

    def assertMoney(self, order, total, tax, untaxed):
        self.assertAlmostEqual(order.amount_total, total, places=2)
        self.assertAlmostEqual(order.amount_tax, tax, places=2)
        self.assertAlmostEqual(order.amount_untaxed, untaxed, places=2)

    def test_company_prices_include_tax(self):
        self.assertEqual(self.company.account_price_include, "tax_included")
        for regime, tax in self.taxes.items():
            with self.subTest(regime=regime):
                self.assertTrue(tax.price_include)
                self.assertFalse(tax.price_include_override, "Налог следует компании.")

    def test_vat_org_150_includes_vat(self):
        order = self._order(self.org_vat)
        line = order.order_line
        self.assertEqual(line.tax_ids, self.taxes["vat22"])
        self.assertAlmostEqual(line.price_unit, 150.0)
        self.assertMoney(order, 150.0, 27.05, 122.95)

    def test_usn_org_150_without_vat(self):
        order = self._order(self.org_usn)
        line = order.order_line
        self.assertEqual(line.tax_ids, self.taxes["usn0"], "Налог режима поверх налога товара.")
        self.assertAlmostEqual(line.price_unit, 150.0, msg="Не 122,95: цена — конечная.")
        self.assertMoney(order, 150.0, 0.0, 150.0)

    def test_org_change_keeps_price(self):
        order = self._order(self.org_vat)
        order.pmk_org_id = self.org_usn
        self.assertEqual(order.order_line.tax_ids, self.taxes["usn0"])
        self.assertAlmostEqual(order.order_line.price_unit, 150.0)
        self.assertMoney(order, 150.0, 0.0, 150.0)
        order.pmk_org_id = self.org_vat
        self.assertEqual(order.order_line.tax_ids, self.taxes["vat22"])
        self.assertAlmostEqual(order.order_line.price_unit, 150.0)
        self.assertMoney(order, 150.0, 27.05, 122.95)

    def test_org_change_in_form_keeps_price(self):
        """Как менеджер в браузере: форма, строка из товара, смена организации."""
        with Form(self.env["sale.order"].with_user(self.manager)) as form:
            form.partner_id = self.client
            form.pmk_org_id = self.org_vat
            with form.order_line.new() as line:
                line.product_id = self.typical
                self.assertAlmostEqual(line.price_unit, 150.0)
            form.pmk_org_id = self.org_usn
            # Итогов в нашей форме нет (вид прячет), цену строки — смотрим.
            with form.order_line.edit(0) as line:
                self.assertAlmostEqual(line.price_unit, 150.0, msg="Смена организации цену не трогает.")
        order = form.record
        self.assertEqual(order.order_line.tax_ids, self.taxes["usn0"])
        self.assertAlmostEqual(order.order_line.price_unit, 150.0)
        self.assertMoney(order, 150.0, 0.0, 150.0)

    def test_kp_and_invoice_agree(self):
        for org, tax_label, tax_amount in (
                (self.org_vat, "в том числе НДС 22%:", 27.05),
                (self.org_usn, "Без НДС (УСН)", None)):
            with self.subTest(org=org.name):
                deal = self._deal(org=org)
                spec = self._spec(deal, org=org, products=[("Кронштейн", 1, 150.0)])
                spec._pmk_kp_move_stage(deal)  # «Отправить КП» (шаг З-9: перенос руками счёт не заводит)
                invoice = self._invoices(deal)
                self.assertEqual(len(invoice), 1)
                self.assertAlmostEqual(invoice.order_line.price_unit, 150.0)
                self.assertAlmostEqual(invoice.amount_total, self._priced_total(spec), places=2,
                                       msg="Итог счёта = итогу КП.")
                label, printed = spec.pmk_print_tax(invoice.amount_total)
                self.assertEqual(label, tax_label)
                if tax_amount is None:
                    self.assertIsNone(printed)
                    self.assertAlmostEqual(invoice.amount_tax, 0.0, places=2)
                else:
                    self.assertAlmostEqual(printed, tax_amount, places=2)
                    self.assertAlmostEqual(invoice.amount_tax, printed, places=2,
                                           msg="Налог счёта = «в том числе» печати КП.")
                self.assertAlmostEqual(invoice.amount_total, 150.0, places=2)
