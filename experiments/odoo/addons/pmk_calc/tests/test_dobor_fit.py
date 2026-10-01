# -*- coding: utf-8 -*-
"""Вписывание эскиза доборки: наименьшая рамка MIN_BOX (01.10.2026).

Построитель (dobor_builder.js, computeFit) и печать (dobor_report.sketch_svg)
вписывают контур по одному правилу. Без нижней рамки почти точечный контур
раздувался в сотни раз — на экране это ломало рисование новой доборки.
Здесь проверяем серверную половину правила: короткая полка не раздувается,
обычный профиль вписывается как раньше.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_calc.models import dobor_report

# Размер листа эскиза и поле под подписи — как в sketch_svg.
W, H, PAD = 470, 300, 86


def _scale(bw, bh, floor):
    return min((W - PAD) / max(floor, bw), (H - PAD) / max(floor, bh))


@tagged("post_install", "-at_install")
class TestDoborFit(TransactionCase):

    def test_min_box_constant(self):
        self.assertEqual(dobor_report.MIN_BOX, 40)

    def test_tiny_flange_is_not_blown_up(self):
        """Полка 5 мм: без рамки масштаб был бы 77 и она легла бы на весь лист."""
        self.assertGreater(_scale(5, 0, 1), 70)
        k = _scale(5, 0, dobor_report.MIN_BOX)
        self.assertLess(5 * k, 40, "Короткая полка остаётся короткой на эскизе.")
        snap = {"start": {"x": 0, "y": 0}, "segs": [{"len": 5, "dir": 0}]}
        self.assertTrue(dobor_report.sketch_svg(snap).startswith("<svg"))

    def test_regular_profile_scale_unchanged(self):
        """85×61 мм — обе стороны больше рамки, масштаб прежний."""
        self.assertAlmostEqual(_scale(85, 61, 1), _scale(85, 61, dobor_report.MIN_BOX))
        snap = {"start": {"x": 0, "y": 0},
                "segs": [{"len": 85, "dir": 0}, {"len": 61, "dir": 90}]}
        self.assertIn("<svg", dobor_report.sketch_svg(snap))
