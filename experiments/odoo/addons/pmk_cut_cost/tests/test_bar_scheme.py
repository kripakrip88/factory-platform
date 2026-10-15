# -*- coding: utf-8 -*-
"""Схема проката во вкладке «Металл»: одинаковые отрезки — одним блоком (15.10.2026)."""
from odoo import Command
from odoo.tests import tagged

from .test_cut_cost import TestCutCost


@tagged("post_install", "-at_install")
class TestBarScheme(TestCutCost):

    def test_overview_and_blocks(self):
        plan = self._plan()
        data = self.spec.pmk_metal_overview()
        rows = {row["material"]: row for row in data["bars"]["rows"]}
        r76 = plan.result_ids.filtered(lambda r: r.profile_id == self.p76)
        row = rows[self.p76.display_name]
        self.assertAlmostEqual(row["buy_kg"], r76.weight_total, places=2)
        self.assertEqual(sum(p["qty"] for p in row["parts"]), 5, "2×2 + 1 отрезка 76×3")
        scheme = self.spec.pmk_metal_bar_scheme(r76.id)
        blocks = scheme["patterns"][0]["blocks"]
        self.assertEqual(blocks, [{"length": 400.0, "qty": 5}], "пять отрезков 400 — одним блоком")
