# -*- coding: utf-8 -*-
"""Запись «Заявка на металл» в истории — таблицей, по строке на позицию (12.10.2026)."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRequestNoteTable(TransactionCase):

    def test_line_cells(self):
        cells = self.env["pmk.metal.spec"]._pmk_request_line_cells
        self.assertEqual(cells("Двутавр 12Б2 — 28,84 м, ≈ 3 хлыста по 12 м, 300 кг"),
                         ("Двутавр 12Б2", "28,84 м, ≈ 3 хлыста по 12 м", "300 кг"))
        self.assertEqual(cells("Лист гладкий 10 мм, 1500 × 6000 — 2 листа, 1,4 т"),
                         ("Лист гладкий 10 мм, 1500 × 6000", "2 листа", "1,4 т"))
        self.assertEqual(cells("Лист рифлёный 5 мм ромб, 1500 × 6000 — 42 листа"),
                         ("Лист рифлёный 5 мм ромб, 1500 × 6000", "42 листа", "—"))
        self.assertEqual(cells("Метизы по месту"), ("Метизы по месту", "—", "—"))
        self.assertEqual(cells(""), ("—", "—", "—"))
        self.assertEqual(cells(False), ("—", "—", "—"))
