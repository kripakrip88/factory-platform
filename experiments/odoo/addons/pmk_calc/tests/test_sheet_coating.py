# -*- coding: utf-8 -*-
"""Лист доборки и вентзонта по цвету (26.10.2026): цинк — оцинкованный, RAL — окрашенный
той же толщины; крашеного такой толщины нет — оцинкованный."""
from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSheetByCoating(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Sheet = cls.env["pmk.metal.sheet"]

        def sheet(kind, t):
            return Sheet.search([("sheet_type", "=", kind), ("thickness_mm", "=", t)], limit=1)

        cls.zn05, cls.pe05 = sheet("Оцинкованный", 0.5), sheet("Окрашенный", 0.5)
        cls.zn065, cls.pe065 = sheet("Оцинкованный", 0.65), sheet("Окрашенный", 0.65)
        cls.zn07 = sheet("Оцинкованный", 0.7)
        assert all((cls.zn05, cls.pe05, cls.zn065, cls.pe065, cls.zn07))
        cls.ral = cls.env.ref("pmk_calc.coating_ral8017")
        cls.zinc = cls.env.ref("pmk_calc.coating_zinc")

    def _dobor(self, sheet, coating):
        order = self.env["pmk.dobor.order"].create({"customer": "Тест цвета", "line_ids": [Command.create({
            "title": "Конёк", "sheet_id": sheet.id, "coating_id": coating.id, "plank_length": 2000.0, "qty": 1})]})
        return order.line_ids

    def test_dobor_ral_goes_painted_and_back(self):
        line = self._dobor(self.zn05, self.ral)
        self.assertEqual(line.sheet_id, self.pe05, "RAL — окрашенный лист той же толщины")
        self.assertEqual(line.thickness, 0.5)
        line.coating_id = self.zinc
        self.assertEqual(line.sheet_id, self.zn05, "цинк — снова оцинкованный")
        line.sheet_id = self.pe065          # выбрали крашеный при цвете «цинк» — поправится
        self.assertEqual(line.sheet_id, self.zn065)

    def test_no_painted_twin_keeps_zinc(self):
        self.assertEqual(self._dobor(self.zn07, self.ral).sheet_id, self.zn07,
                         "крашеного 0,7 в справочнике нет — лист не меняется")

    def test_vent_hood(self):
        order = self.env["pmk.vent.hood.order"].create({"line_ids": [
            Command.create({"width": 400, "length": 600, "qty": 1, "coating_id": self.ral.id}),
            Command.create({"width": 400, "length": 600, "qty": 1, "coating_id": self.zinc.id})]})
        ral, zinc = order.line_ids.sorted("id")
        self.assertEqual(ral.sheet_id, self.pe065, "умолчание 0,65 оцинк + RAL → окрашенный 0,65")
        self.assertEqual(zinc.sheet_id, self.zn065)
        self.assertEqual(ral.thickness, 0.65)

    def test_onchange(self):
        line = self.env["pmk.dobor.order.line"].new({"sheet_id": self.zn05.id, "coating_id": self.ral.id})
        line._onchange_pmk_sheet_by_coating()
        self.assertEqual(line.sheet_id, self.pe05)
