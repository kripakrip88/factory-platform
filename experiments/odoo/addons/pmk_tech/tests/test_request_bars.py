# -*- coding: utf-8 -*-
"""«Заявка на металл»: прокат — целыми хлыстами из раскроя сортамента
(Антон 15.10.2026: поставщики «продают целыми»)."""
from odoo.tests import tagged

from .test_step_z4 import Z4Common


@tagged("post_install", "-at_install")
class TestRequestBars(Z4Common):

    def test_linear_rows_from_cut_plan(self):
        if "pmk.cut.plan" not in self.env:
            self.skipTest("нужен pmk_cut")
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        before = {r["position"]: r for r in tech._pmk_metal_rows()[0]}
        self.assertAlmostEqual(before[self.angle]["qty"], 6.0, places=2, msg="без раскроя — чистые метры")
        plan = self.env["pmk.cut.plan"].create({"spec_id": tech.id})
        plan.action_fill_from_spec()
        plan.action_compute()
        rows = {r["position"]: r for r in tech._pmk_metal_rows()[0]}
        angle = rows[self.angle]
        self.assertAlmostEqual(angle["qty"], 12.0, places=2, msg="6 м отрезков — целый хлыст 12 м")
        self.assertAlmostEqual(angle["kg"], 120.0, places=1)
        self.assertAlmostEqual(angle["price"], 1000.0, places=2, msg="цена за метр по прайсу")
        self.assertIn("1 хлыст по 12 м", angle["label"])
