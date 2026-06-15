# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

try:
	from frappe.tests import IntegrationTestCase as _Base
except Exception:  # pragma: no cover
	from unittest import TestCase as _Base

from metal_calculator.cutting.sheet import plan_sheet


def _item(sl, length, width, qty):
	return {"size_label": sl, "piece_length": length, "piece_width": width, "qty": qty}


class TestCuttingSheet(_Base):
	def test_exact_fit_no_waste(self):
		"""Лист 1000×1000, kerf 0, 500×500 ×4 → 1 лист, отход 0%."""
		r = plan_sheet(1000, 1000, 0, [_item("4", 500, 500, 4)])
		self.assertEqual(r["total_stock"], 1)
		self.assertEqual(r["waste_percent"], 0.0)

	def test_two_sheets_when_no_fit(self):
		"""Лист 1000×1000, 600×600 ×2 → по ширине 1, по высоте 2 не лезут → 2 листа."""
		r = plan_sheet(1000, 1000, 0, [_item("4", 600, 600, 2)])
		self.assertEqual(r["total_stock"], 2)

	def test_rotation_90(self):
		"""Лист 1000×400, деталь 300×800 → в исходной не лезет, повёрнутая лезет → 1 лист."""
		r = plan_sheet(1000, 400, 0, [_item("4", 300, 800, 1)])
		self.assertEqual(r["total_stock"], 1)
		self.assertIsNone(r["groups"][0]["error"])

	def test_oversize_marks_error(self):
		"""Деталь 1200×500 при листе 1000×1000 → не влезает ни в одной ориентации → ошибка."""
		r = plan_sheet(1000, 1000, 0, [_item("4", 1200, 500, 1)])
		self.assertIsNotNone(r["groups"][0]["error"])
		self.assertEqual(r["total_stock"], 0)

	def test_waste_area_arithmetic(self):
		"""Лист 1000×1000, деталь 500×1000 ×1 → отход 50%."""
		r = plan_sheet(1000, 1000, 0, [_item("4", 500, 1000, 1)])
		self.assertEqual(r["total_stock"], 1)
		self.assertEqual(r["waste_percent"], 50.0)

	def test_thicknesses_separate(self):
		"""Разные толщины раскраиваются отдельными группами."""
		r = plan_sheet(1000, 1000, 0, [_item("4", 500, 500, 1), _item("6", 500, 500, 1)])
		self.assertEqual(len(r["groups"]), 2)
		self.assertEqual(r["total_stock"], 2)
