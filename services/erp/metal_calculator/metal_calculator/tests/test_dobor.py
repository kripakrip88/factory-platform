# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

try:
	from frappe.tests import IntegrationTestCase as _Base
except Exception:  # pragma: no cover
	from unittest import TestCase as _Base

from metal_calculator.dobor.api import compute

MPS_05 = 0.5 * 7.85  # масса 1 м² для стали 0.5 мм


def _f(*lens):
	return [{"len": L, "dir": 0} for L in lens]


class TestDobor(_Base):
	def test_developed_with_hem(self):
		"""Полки 50+40+50 + завальцовка 15 (слева) → развёртка 155."""
		r = compute(_f(50, 40, 50), True, False, 15, MPS_05, 2500, 1)
		self.assertEqual(r["developed_width"], 155)

	def test_area_and_weight(self):
		"""Развёртка 155, длина 2500, толщина 0.5 → площадь 0.3875 м², вес 1.521 кг."""
		r = compute(_f(50, 40, 50), True, False, 15, MPS_05, 2500, 1)
		self.assertAlmostEqual(r["area_one"], 0.3875, places=4)
		self.assertAlmostEqual(r["weight_one"], 0.3875 * MPS_05, places=3)

	def test_weight_total_qty(self):
		r = compute(_f(50, 40, 50), True, False, 15, MPS_05, 2500, 10)
		self.assertAlmostEqual(r["weight_total"], 10 * 0.3875 * MPS_05, places=3)

	def test_no_hem_developed(self):
		"""Без завальцовки развёртка = сумма полок (поправка на гиб не применяется)."""
		r = compute(_f(50, 40, 50), False, False, 15, MPS_05, 2500, 1)
		self.assertEqual(r["developed_width"], 140)

	def test_two_hems_count_as_bends(self):
		"""3 полки + 2 завальцовки → гибов = (3-1) + 2 = 4; развёртка = 140 + 2×15 = 170."""
		r = compute(_f(50, 40, 50), True, True, 15, MPS_05, 2500, 1)
		self.assertEqual(r["bends"], 4)
		self.assertEqual(r["developed_width"], 170)

	def test_strips_from_coil(self):
		"""Развёртка 155, рулон 1250 → полос floor(1250/155)=8, отход 1250-8×155=10 мм."""
		r = compute(_f(50, 40, 50), True, False, 15, MPS_05, 2500, 1, coil_width=1250)
		self.assertEqual(r["strips"], 8)
		self.assertEqual(r["strip_waste"], 10)

	def test_lock_adds_two_bends(self):
		"""Замок добавляет 2 гиба: 3 полки + 1 завальцовка + замок → гибов = 2+1+2 = 5."""
		r = compute(_f(50, 40, 50), True, False, 15, MPS_05, 2500, 1, lock=True)
		self.assertEqual(r["bends"], 5)
		# без замка тот же профиль — 3 гиба
		self.assertEqual(compute(_f(50, 40, 50), True, False, 15, MPS_05, 2500, 1)["bends"], 3)
