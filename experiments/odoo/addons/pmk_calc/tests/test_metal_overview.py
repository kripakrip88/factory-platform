# -*- coding: utf-8 -*-
"""Вкладка «Металл» одной таблицей с раскрытием и схемой (15.10.2026)."""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged

from ..models import sheeting


def _overlaps(rects):
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if (a[1] < b[1] + b[3] - 0.01 and b[1] < a[1] + a[3] - 0.01
                    and a[2] < b[2] + b[4] - 0.01 and b[2] < a[2] + a[4] - 0.01):
                return True
    return False


@tagged("post_install", "-at_install")
class TestSheetDrawings(TransactionCase):
    """Схема листа — та же раскладка, что число листов (sheeting.group_drawings)."""

    def test_counts_match_plan(self):
        for parts in ([(1, 90, 460, 500)], [(1, 300, 200, 16), (2, 150, 120, 32)],
                      [(1, 560, 6000, 67), (2, 120, 6000, 60)], [(1, 1500, 6000, 3)],
                      [(1, 700, 1300, 9), (2, 333, 250, 25), (3, 95, 95, 200)]):
            plan = sheeting.plan_group(1500, 6000, parts)
            result = sheeting.group_drawings(1500, 6000, parts)
            self.assertEqual(result["sheets"], plan["sheets"])
            self.assertEqual(sum(d["count"] for d in result["drawings"]) + result["more"], plan["sheets"])
            placed = {}
            for drawing in result["drawings"]:
                self.assertFalse(_overlaps(drawing["rects"]), parts)
                for key, x, y, w, l in drawing["rects"]:
                    self.assertGreaterEqual(x, -0.01)
                    self.assertLessEqual(x + w, 1500 + 5.01)
                    self.assertLessEqual(y + l, 6000 + 5.01)
                    placed[key] = placed.get(key, 0) + drawing["count"]
            if not result["more"]:
                self.assertEqual(placed, {key: qty for key, _a, _b, qty in parts}, "все детали на схеме")

    def test_single_matches_fit_sheet(self):
        for a, b in ((90, 460), (500, 500), (333, 250), (1200, 700)):
            count = sheeting.fit_sheet(1500, 6000, a, b)[0]
            self.assertEqual(len(sheeting.single_placements(1500, 6000, a, b)), count)


@tagged("post_install", "-at_install")
class TestMetalOverview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест вкладки)", "thickness_mm": 10.0,
            "gost": "ГОСТ тест", "mass_per_sqm": 78.5})
        cls.spec = cls.env["pmk.metal.spec"].with_context(mail_create_nolog=True).create({
            "product_ids": [Command.create({
                "name": "Опора (тест вкладки)", "qty": 2,
                "line_ids": [
                    Command.create({"calc_mode": "sheet", "sheet_id": cls.sheet.id,
                                    "detail_name": "Пластина", "a_mm": 300.0, "b_mm": 200.0, "qty": 8}),
                    Command.create({"calc_mode": "sheet", "sheet_id": cls.sheet.id,
                                    "detail_name": "Ребро", "a_mm": 150.0, "b_mm": 120.0, "qty": 16}),
                ]})]})

    def test_overview_before_layout(self):
        data = self.spec.pmk_metal_overview()
        self.assertEqual(data["sheets"], [])
        self.assertEqual(len(data["loose"]), 2, "без раскладки — «Не разложено»")

    def test_overview_and_scheme(self):
        self.spec.action_draft_layout()
        data = self.spec.pmk_metal_overview()
        self.assertEqual(len(data["sheets"]), 1)
        row = data["sheets"][0]
        self.assertEqual(row["sheets_buy"], 1)
        self.assertAlmostEqual(row["buy_kg"], 1.5 * 6.0 * 78.5, places=1, msg="целый лист 1500×6000")
        self.assertEqual({p["name"]: p["qty"] for p in row["parts"]}, {"Пластина": 16, "Ребро": 32})
        scheme = self.spec.pmk_metal_sheet_scheme(row["id"])
        self.assertEqual(sum(d["count"] for d in scheme["drawings"]), 1)
        self.assertEqual(len(scheme["drawings"][0]["rects"]), 48, "все 48 деталей на листе")
        self.spec.pmk_metal_set_sheet_size(row["parts"][0]["id"], "1500x3000")
        self.assertEqual(self.spec.sheet_line_ids.sorted("id")[0].layout_sheet_size, "1500x3000")

    def test_widget_in_metal_tab(self):
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_view(view_type="form")["arch"])
        page = arch.xpath("//page[@name='layout']")[0]
        self.assertEqual(page[0].tag, "widget")
        self.assertEqual(page[0].get("name"), "pmk_metal_overview")
        self.assertEqual(page.xpath("./field[@name='sheet_line_ids']")[0].get("invisible"), "1")
