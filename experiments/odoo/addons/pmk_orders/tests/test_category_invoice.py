# -*- coding: utf-8 -*-
"""Счёт из расчёта с категориями (12.10.2026): доборки и вентзонты с ручной ценой — строками
счёта; черновик идёт за ними так же, как за изделиями расчёта."""
import json

from odoo import Command
from odoo.tests import tagged

from .test_step_z2_invoice import Z2Common

SNAP = json.dumps({"start": {"x": 0, "y": 0}, "segs": [{"len": 120, "dir": 0}, {"len": 80, "dir": 90}]})


@tagged("post_install", "-at_install")
class TestCategoryInvoice(Z2Common):

    def test_dobor_and_vent_lines_in_invoice(self):
        deal = self._deal()
        spec = self._spec(deal, products=[("Ферма Ф-1", 2, 1000.0)], cat_dobor=True, cat_vent=True)
        dobor, vent = spec.dobor_order_ids.sudo(), spec.vent_order_ids.sudo()
        self.assertEqual(dobor.opportunity_id, deal, "сделка расчёта — в его доборку")
        coat = self.env.ref("pmk_calc.coating_ral8017")
        dobor.write({"line_ids": [Command.create({"title": "Отлив", "coating_id": coat.id, "plank_length": 2000.0,
                                                  "qty": 5, "price_unit": 300.0, "profile_snapshot_json": SNAP}),
                                  Command.create({"title": "Без цены", "coating_id": coat.id, "plank_length": 2000.0,
                                                  "qty": 1, "profile_snapshot_json": SNAP})]})
        vent.write({"line_ids": [Command.create({"width": 500, "length": 1000, "qty": 2, "coating_id": coat.id,
                                                 "price_unit": 1500.0})]})
        spec.with_user(self.manager).action_pmk_invoice()
        invoice = self._invoices(deal)
        lines = invoice.order_line.filtered("pmk_from_spec").sorted("sequence")
        self.assertEqual(len(lines), 3, "изделие + доборка с ценой + зонт; без цены — не в счёте")
        self.assertEqual(lines[1].pmk_dobor_line_id.title, "Отлив")
        self.assertIn("Доборный элемент «Отлив»", lines[1].name)
        self.assertEqual((lines[1].product_uom_qty, lines[1].price_unit), (5, 300.0))
        self.assertTrue(lines[2].pmk_vent_line_id)
        self.assertIn("Вентзонт", lines[2].name)
        self.assertIn("Без цены", invoice.pmk_skip_text or "")

        # Черновик идёт за доборкой: цену поменяли — строка счёта следом.
        dobor.line_ids.filtered(lambda l: l.title == "Отлив").price_unit = 350.0
        self.assertEqual(lines[1].price_unit, 350.0)
        # Категорию выключили — строки зонтов из черновика ушли.
        spec.cat_vent = False
        self.assertFalse(invoice.order_line.filtered("pmk_vent_line_id"))
