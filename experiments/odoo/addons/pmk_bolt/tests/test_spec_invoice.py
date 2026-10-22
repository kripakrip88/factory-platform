# -*- coding: utf-8 -*-
"""Болты в расчёте и счёте (21.10.2026): категория, вкладка, сводка, счёт из расчёта."""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.pmk_orders.tests.test_step_z2_invoice import Z2Common


@tagged("post_install", "-at_install")
class TestBoltInSpecAndInvoice(Z2Common):

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env["pmk.bolt.line"]), "_pmk_ref_price_ton",
                               lambda line, record, grade=None: 90000.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _bolt_spec(self, deal=None):
        deal = deal or self._deal()
        spec = self._spec(deal, products=[("Ферма Ф-1", 2, 1000.0)])
        spec.cat_bolt = True
        rows = spec.bolt_rows()["rows"]
        spec.bolt_save_row(rows[0]["id"], {"name": "бф 2.1 м30 600 09г2с 16шт гайка 45"})
        line = spec.bolt_calc_ids.line_ids.filtered("name")
        line.part_ids.filtered(lambda p: p.auto_key == "washer")._pmk_user_write({"price_unit": 30})
        return deal, spec, line

    def test_category_tab_and_summary(self):
        _deal, spec, line = self._bolt_spec()
        self.assertEqual(len(spec.bolt_calc_ids), 1)
        self.assertEqual(spec.bolt_calc_ids.partner_id, spec.partner_id)
        self.assertEqual(line.qty, 16)
        bolt = next(r for r in spec.pmk_summary["rows"] if r["source"] == "bolt")
        self.assertIn("тип 2.1 М-30х600", bolt["name"])
        self.assertEqual([d["name"][:5] for d in bolt["details"]], ["Круг ", "Гайка", "Шайба", "Плита"])
        # Выключили — черновик: в сводку не идёт, документ цел.
        spec.cat_bolt = False
        self.assertTrue(spec.bolt_calc_ids)
        self.assertFalse([r for r in spec.pmk_summary["rows"] if r["source"] == "bolt"])
        # Копия расчёта — с копией болтов.
        spec.cat_bolt = True
        copy = spec.copy()
        self.assertEqual(copy.bolt_calc_ids.line_ids.filtered("name").mapped("name"), [line.name])

    def test_invoice_from_spec_follows_bolt(self):
        deal, spec, line = self._bolt_spec()
        spec.with_user(self.manager).action_pmk_invoice()
        invoice = self._invoices(deal)
        bolt_line = invoice.order_line.filtered("pmk_bolt_line_id")
        self.assertEqual(bolt_line.name, line.name)
        self.assertEqual((bolt_line.product_uom_qty, bolt_line.price_unit), (16, line.price_unit))
        # Цена болта поменялась — черновик следом.
        line.price_unit = 2500
        self.assertEqual(bolt_line.price_unit, 2500)
        line.qty = 20
        self.assertEqual(bolt_line.product_uom_qty, 20)
        # Без цены — в «без цены клиенту», не в счёте.
        line.price_unit = 0
        self.assertFalse(invoice.order_line.filtered("pmk_bolt_line_id"))
        self.assertIn(line.short_name, invoice.pmk_skip_text or "")

    def test_invoice_menu_bolts(self):
        deal = self._deal()
        spec = self._spec(deal, products=[("Секция ограждения ОГ-1", 2, 4500.0)])
        spec.with_user(self.manager).action_pmk_invoice()
        invoice = self._invoices(deal)
        keys = [i["key"] for i in invoice.pmk_doc_menu()["create"]]
        self.assertIn("bolts", keys)
        action = invoice.action_pmk_doc_bolts()
        self.assertTrue(spec.cat_bolt)
        self.assertEqual(action.get("res_id"), spec.id)

    def test_header_with_bolts(self):
        """Шапка расчёта (22.10.2026): цена, себестоимость, вес и «нет цены» — с болтами."""
        _deal, spec, line = self._bolt_spec()
        products = sum(spec.product_ids.mapped("price_customer_total"))
        self.assertAlmostEqual(spec.price_customer_total, products + line.price_total, places=2)
        self.assertAlmostEqual(spec.cost_all_total, spec.total_cost_fact + line.cost_one * line.qty, places=2)
        self.assertAlmostEqual(spec.margin_amount, spec.price_customer_total - spec.cost_all_total, places=2)
        self.assertEqual(spec.price_uncosted, 0)
        self.assertAlmostEqual(spec.total_weight, sum(spec.product_ids.mapped("weight_total"))
                               + line.mass_one * line.qty, places=2)
        self.assertEqual(spec.total_products, len(spec.product_ids) + 1)
        before = spec.no_price_count
        # Шайба без цены — себестоимость занижена: «нет цены» в шапке с названием.
        line.part_ids.filtered(lambda p: p.auto_key == "washer")._pmk_user_write({"price_unit": 0})
        self.assertEqual(spec.no_price_count, before + 1)
        self.assertTrue(spec.price_incomplete)
        self.assertIn("Шайба", spec.price_missing_text)
        # Болты выключили — шапка без них.
        spec.cat_bolt = False
        self.assertAlmostEqual(spec.price_customer_total, products, places=2)
        self.assertEqual(spec.no_price_count, before)

    def test_xlsx_composition_bolts(self):
        """«Расчёт (Excel)»: на листе «Состав» — раздел болтов с составом."""
        import io
        from openpyxl import load_workbook
        _deal, spec, line = self._bolt_spec()
        book = load_workbook(io.BytesIO(spec._pmk_xlsx()))
        cells = [str(c.value) for row in book["Состав"].iter_rows() for c in row if c.value]
        self.assertIn("Фундаментные болты", cells)
        self.assertIn(line.name, cells)
        self.assertTrue(any(c.startswith("Круг 30") for c in cells))
        money = [str(c.value) for row in book["Металл и деньги"].iter_rows() for c in row if c.value]
        self.assertTrue(any(c.startswith("Гайка М30") for c in money))
