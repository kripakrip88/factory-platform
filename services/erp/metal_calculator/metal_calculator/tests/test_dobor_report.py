# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

try:
	from frappe.tests import IntegrationTestCase as _Base
except Exception:  # pragma: no cover
	from unittest import TestCase as _Base

from metal_calculator.dobor.report import sketch_svg, item_numbers, _flange


SNAP = {
	"start": {"x": 0, "y": 0},
	"segs": [{"len": 50, "dir": -90}, {"len": 40, "dir": 0}, {"len": 50, "dir": 90}],
	"hemLeft": True, "hemRight": False, "hemLeftDir": 1, "hemRightDir": -1, "hemLen": 15,
}


class TestDoborReport(_Base):
	def test_numbers_match_compute(self):
		"""Числа листа = серверный compute: развёртка 50+40+50+15=155, гибов (3-1)+1=3."""
		r = item_numbers(SNAP, 0.5, 2500, 10)
		self.assertEqual(r["developed_width"], 155)
		self.assertEqual(r["bends"], 3)
		self.assertEqual(r["flanges_count"], 3)
		self.assertAlmostEqual(r["weight_total"], 10 * 0.3875 * 0.5 * 7.85, places=2)

	def test_sketch_svg_renders(self):
		"""Эскиз — валидный SVG с подписями длин полок и углов."""
		svg = sketch_svg(SNAP)
		self.assertTrue(svg.startswith("<svg"))
		self.assertIn("</svg>", svg)
		# по подписи на каждую полку (крупный шрифт для печати)
		self.assertEqual(svg.count('font-size="19"'), 3)
		# угол между полками (домик из П → у среднего гиба тупой угол)
		self.assertIn("°", svg)
		# пунктир стороны покрытия
		self.assertIn("stroke-dasharray", svg)

	def test_sketch_empty_safe(self):
		"""Пустой профиль не падает."""
		self.assertEqual(sketch_svg({"segs": []}), "")

	def test_flange_between(self):
		"""flange = 180 − |отклонение|: прямой угол даёт 90°."""
		self.assertEqual(round(_flange(SNAP["segs"], 1)), 90)
