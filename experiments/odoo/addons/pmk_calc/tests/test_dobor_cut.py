# -*- coding: utf-8 -*-
"""Раскрой листа доборки (12.10.2026): гильотина, стандарт 1250 × 2500 / с бухты, до 2500 мм."""
import json

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_calc.tools import dobor_cut as C

SNAPSHOT = json.dumps({"start": {"x": 0, "y": 0},
                       "segs": [{"len": 85, "dir": 0}, {"len": 61, "dir": 90}, {"len": 20, "dir": 180}]})


@tagged("post_install", "-at_install")
class TestDoborCut(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Оцинкованный", "thickness_mm": 0.7,
            "gost": "ГОСТ 14918-2020 (тест раскроя)", "mass_per_sqm": 5.495})
        cls.coating = cls.env["pmk.dobor.coating"].create({
            "name": "RAL 8017 (тест раскроя)", "ral_code": "8017", "hex_color": "#45322e"})

    # ---------------------------------------------------------------- алгоритм
    def test_full_sheet_strips(self):
        """Развёртка 250 × 2500: пять в ширину листа, 10 штук — ровно 2 листа без отхода."""
        r = C.plan([(250, 2500, "№1", 10)], 5.0)
        self.assertEqual(r["stock"]["sheets"], 2)
        self.assertEqual(r["stock"]["util_pct"], 100.0)
        self.assertEqual(r["coil"]["lengths"], "2500 × 2")
        self.assertEqual(r["recommend"], "stock", "бухте нечего сэкономить")

    def test_coil_cuts_length(self):
        """Планка 2000: со стандарта остаётся 500 мм на листе, с бухты — лист 2000."""
        r = C.plan([(250, 2000, "№1", 5)], 5.0)
        self.assertEqual(r["stock"]["lengths"], "2500")
        self.assertEqual(r["coil"]["lengths"], "2000")
        self.assertAlmostEqual(r["saving"]["kg"], 1.25 * 0.5 * 5.0, places=1)
        self.assertEqual(r["recommend"], "coil")

    def test_short_planks_share_sheet(self):
        """Ленты 1200 и 1300 — в один лист 2500 поперёк."""
        r = C.plan([(1250, 1200, "№1", 1), (1250, 1300, "№2", 1)], 5.0)
        self.assertEqual(r["stock"]["sheets"], 1)
        self.assertEqual(len(r["stock"]["maps"][0]["bands"]), 2)

    def test_coil_length_step_50(self):
        r = C.plan([(300, 2230, "№1", 1)], 5.0)
        self.assertEqual(r["coil"]["lengths_mm"], [2250.0])

    def test_short_plank_across_sheet(self):
        """Планка 1250 = ширина листа: рубится сразу поперёк полосой 150 × 1250, без отхода
        по ширине (Антон 12.10.2026). С бухты — ровно 150 мм на штуку."""
        self.assertEqual(C.orient(150, 1250), (1250, 150))
        self.assertEqual(C.orient(166, 2000), (166, 2000), "длиннее 1250 — только вдоль")
        r = C.plan([(150, 1250, "№3", 10)], 5.0)
        self.assertEqual(r["coil"]["lengths"], "150 × 10", "готовые заготовки с бухты")
        self.assertEqual((r["coil"]["sheets"], r["coil"]["ready"]), (0, 10))
        self.assertEqual(r["coil"]["util_pct"], 100.0)
        self.assertEqual(C.card_steps(r["coil"]["maps"][0]),
                         ["Готовая заготовка №3 (150×1250) — лист 1250 × 150, резать не нужно"])
        # Со стандартного листа — полосы поперёк, 16 на лист.
        self.assertIn("Полоса 150 мм поперёк листа — сразу заготовка №3 (150×1250) — 10 раз",
                      C.card_steps(r["stock"]["maps"][0]))

    def test_coil_sheet_per_band(self):
        """С бухты лист = лента: листы 2000 для планок 2000, не 2450 вперемешку (Антон 12.10.2026)."""
        r = C.plan([(166, 2000, "№1", 14), (150, 1250, "№3", 3)], 5.0)
        self.assertEqual(r["coil"]["lengths"], "2000 × 2 + 150 × 3")
        self.assertEqual(r["coil"]["ready_lengths"], "150 × 3")

    def test_limits(self):
        with self.assertRaises(C.CutError):
            C.plan([(200, 2600, "№1", 1)], 5.0)
        with self.assertRaises(C.CutError):
            C.plan([(1300, 1000, "№1", 1)], 5.0)

    def test_identical_sheets_one_map(self):
        r = C.plan([(250, 2500, "№1", 15)], 5.0)
        self.assertEqual(r["stock"]["sheets"], 3)
        self.assertEqual([m["count"] for m in r["stock"]["maps"]], [3])
        self.assertIn("<svg", C.sheet_svg(r["stock"]["maps"][0]))

    # ---------------------------------------------------------------- в заказе
    def _order(self, length=2000.0, qty=4):
        return self.env["pmk.dobor.order"].create({"line_ids": [Command.create({
            "title": "Планка", "coating_id": self.coating.id, "sheet_id": self.sheet.id,
            "plank_length": length, "qty": qty, "profile_snapshot_json": SNAPSHOT})]})

    def test_order_tab(self):
        order = self._order()
        self.assertEqual(order.cut_source, "stock", "обычно — стандартный лист")
        html = str(order.cut_html)
        self.assertIn("RAL 8017 (тест раскроя)", html)
        self.assertIn("Стандарт 1250 × 2500", html)
        self.assertIn("С бухты", html)
        self.assertIn("<svg", html)
        self.assertIn("№1", html)
        order.cut_source = "coil"
        self.assertIn('class="pmk-cut-chosen"><th>С бухты', str(order.cut_html))

    def test_print_bw(self):
        order = self._order()
        html = str(order._cut_print_html())
        self.assertIn("Раскрой листа · %s" % order.name, html)
        self.assertIn("Карта 1", html)
        self.assertIn("Лента 2000 мм поперёк листа", html)
        self.assertIn("<svg", html)
        for colour in ("#dfe9c4", "#f3f1ec", "#5d6b2a"):
            self.assertNotIn(colour, html, "печать чёрно-белая — без цветных заливок")
        # Действие печати в тестовой базе может вернуть окно «нет wkhtmltopdf» — сверяем отчёт.
        report = self.env.ref("pmk_calc.action_report_dobor_cut")
        self.assertEqual((report.model, report.report_name), ("pmk.dobor.order", "pmk_calc.report_dobor_cut"))
        self.assertTrue(order.action_print_cut())

    def test_plank_over_2500_forbidden(self):
        with self.assertRaises(ValidationError):
            self._order(length=2600.0)
