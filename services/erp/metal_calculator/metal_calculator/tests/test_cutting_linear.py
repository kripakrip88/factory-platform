# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

try:
	from frappe.tests import IntegrationTestCase as _Base
except Exception:  # pragma: no cover
	from unittest import TestCase as _Base

from metal_calculator.cutting.linear import plan_linear


def _item(pt, sl, length, qty):
	return {"profile_type": pt, "size_label": sl, "piece_length": length, "qty": qty}


class TestCuttingLinear(_Base):
	def test_no_kerf_exact_fit(self):
		"""Хлыст 6000, kerf 0, 2000×3 → 1 хлыст, отход 0%."""
		r = plan_linear(6000, 0, [_item("Труба", "40x40x3", 2000, 3)])
		self.assertEqual(r["total_stock"], 1)
		self.assertEqual(r["waste_percent"], 0.0)

	def test_kerf_forces_second_stock(self):
		"""Хлыст 6000, kerf 5, 2000×3 → 2000+5 не лезут трижды → 2 хлыста."""
		r = plan_linear(6000, 5, [_item("Труба", "40x40x3", 2000, 3)])
		self.assertEqual(r["total_stock"], 2)

	def test_piece_longer_than_stock_marks_error(self):
		"""Деталь 7000 при хлысте 6000 → ошибка группы, расчёт не падает."""
		r = plan_linear(6000, 0, [_item("Уголок", "50x50x5", 7000, 1)])
		self.assertIsNotNone(r["groups"][0]["error"])
		self.assertEqual(r["total_stock"], 0)

	def test_each_sortament_separately(self):
		"""Каждый сортамент раскраивается отдельной группой."""
		r = plan_linear(6000, 0, [_item("Труба", "A", 3000, 2), _item("Уголок", "B", 3000, 2)])
		self.assertEqual(len(r["groups"]), 2)
		self.assertEqual(r["total_stock"], 2)

	def test_waste_arithmetic(self):
		"""Хлыст 6000, 2000×2 → 1 хлыст, отход (6000-4000)/6000 = 33.33%."""
		r = plan_linear(6000, 0, [_item("Труба", "A", 2000, 2)])
		self.assertEqual(r["total_stock"], 1)
		self.assertAlmostEqual(r["waste_percent"], 33.33, places=1)
