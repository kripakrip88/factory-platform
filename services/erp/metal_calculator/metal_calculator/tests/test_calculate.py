# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

import frappe

try:
	# frappe v16
	from frappe.tests import IntegrationTestCase as _BaseTestCase
except Exception:  # pragma: no cover - совместимость со старыми версиями
	from frappe.tests.utils import FrappeTestCase as _BaseTestCase

from metal_calculator.api import calculate
from metal_calculator.seed import seed_all


class TestCalculate(_BaseTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Справочники должны существовать для расчёта (идемпотентно).
		seed_all()

	def _sheet_name(self, thickness):
		# Толщина теперь не уникальна (гладкий/рифлёный/ПВЛ) — берём гладкий.
		return frappe.db.get_value(
			"Metal Sheet Grade", {"thickness": thickness, "sheet_type": "Гладкий"}, "name"
		)

	# --- Якоря из ТЗ ---

	def test_dvutavr_20b1(self):
		"""Двутавр 20Б1 (21.3 кг/м), L=6000 мм, n=10 → 1278 кг."""
		res = calculate(mode="linear", ref="Двутавр-20Б1", qty=10, length_mm=6000)
		self.assertAlmostEqual(res["weight_one_kg"], 127.8, places=2)
		self.assertAlmostEqual(res["weight_total_kg"], 1278.0, places=1)

	def test_shveller_16u(self):
		"""Швеллер 16У (14.2 кг/м), L=6000 мм, n=1 → 85.2 кг."""
		res = calculate(mode="linear", ref="Швеллер-16У", qty=1, length_mm=6000)
		self.assertAlmostEqual(res["weight_total_kg"], 85.2, places=1)

	def test_sheet_t4(self):
		"""Лист t=4 мм (31.4 кг/м²), 1500×6000 мм, n=1 → 282.6 кг."""
		ref = self._sheet_name(4)
		self.assertIsNotNone(ref, "Лист 4 мм должен быть в справочнике")
		res = calculate(mode="sheet", ref=ref, qty=1, a_mm=1500, b_mm=6000)
		self.assertAlmostEqual(res["weight_total_kg"], 282.6, places=1)

	def test_truba_profilnaya_split(self):
		"""Трубы профильные разделены: квадратная и прямоугольная — разные группы."""
		sq = frappe.db.get_value(
			"Metal Profile",
			{"profile_type": "Труба профильная квадратная", "size_label": "40x40x3"},
			"name",
		)
		rect = frappe.db.get_value(
			"Metal Profile",
			{"profile_type": "Труба профильная прямоугольная", "size_label": "60x40x2"},
			"name",
		)
		self.assertEqual(sq, "Труба профильная квадратная-40x40x3")
		self.assertEqual(rect, "Труба профильная прямоугольная-60x40x2")
		res = calculate(mode="linear", ref=sq, qty=1, length_mm=6000)
		self.assertAlmostEqual(res["weight_total_kg"], 20.16, places=2)  # 3.36×6

	def test_sheet_types_distinct(self):
		"""Гладкий/рифлёный/ПВЛ с толщиной 4 — разные записи, разные имена."""
		flat = frappe.db.get_value(
			"Metal Sheet Grade", {"thickness": 4, "sheet_type": "Гладкий"}, "name"
		)
		pvl = frappe.db.get_value(
			"Metal Sheet Grade", {"sheet_type": "Просечно-вытяжной", "size_label": "406"}, "name"
		)
		self.assertEqual(flat, "Лист-4мм")
		self.assertEqual(pvl, "ПВЛ-406")
		# ПВЛ 406 = 15.7 кг/м², лист 1×1 м → 15.7 кг
		res = calculate(mode="sheet", ref=pvl, qty=1, a_mm=1000, b_mm=1000)
		self.assertAlmostEqual(res["weight_total_kg"], 15.7, places=2)

	# --- Контроль конвертации мм→м ---

	def test_mm_conversion_guard(self):
		"""Тот же двутавр с L=6 (как будто метры) НЕ должен давать 1278."""
		res = calculate(mode="linear", ref="Двутавр-20Б1", qty=10, length_mm=6)
		self.assertFalse(
			abs(res["weight_total_kg"] - 1278.0) < 1.0,
			"Похоже, забыта конвертация мм→м: вес завышен в ~1000 раз",
		)
		self.assertAlmostEqual(res["weight_total_kg"], 1.278, places=3)

	# --- Марка стали не влияет на вес ---

	def test_steel_grade_does_not_affect_weight(self):
		base = calculate(mode="linear", ref="Швеллер-16У", qty=1, length_mm=6000)
		with_grade = calculate(
			mode="linear", ref="Швеллер-16У", qty=1, length_mm=6000, steel_grade="09Г2С"
		)
		self.assertEqual(base["weight_total_kg"], with_grade["weight_total_kg"])
		self.assertEqual(with_grade["steel_grade"], "09Г2С")

	# --- Валидация входа ---

	def test_zero_qty_raises(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			calculate(mode="linear", ref="Швеллер-16У", qty=0, length_mm=6000)

	def test_negative_length_raises(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			calculate(mode="linear", ref="Швеллер-16У", qty=1, length_mm=-1)

	def test_unknown_profile_raises(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			calculate(mode="linear", ref="Несуществующий-профиль", qty=1, length_mm=6000)

	def test_unknown_mode_raises(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			calculate(mode="bogus", ref="Швеллер-16У", qty=1, length_mm=6000)
