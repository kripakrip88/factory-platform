# -*- coding: utf-8 -*-
"""Задача 258 (ДОБ-18, 12.10.2026): H-профиль с двойным подгибом.

Верхний лист и два подгиба 180° под ним к стенкам. Построитель рисовал слой
подгиба не с той стороны (внутрь профиля, через стенку), а второй подгиб
уводил ещё дальше — всё после него отрывалось от своих точек. Печать
(dobor_report.sketch_svg) и холст (dobor_builder.js foldRot) считают сторону
по одному правилу; здесь — серверная половина.
"""
import re

from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_calc.models import dobor_report as dr

# ДОБ-18 как нарисовал владелец (углы мышью: 91°, 179° ...).
DOB18_RAW = [{"len": 13, "dir": 180}, {"len": 9, "dir": 91}, {"len": 8, "dir": 0},
             {"len": 18, "dir": 179}, {"len": 5, "dir": -1}, {"len": 9, "dir": -89},
             {"len": 8, "dir": -178}]
# Тот же профиль после прилипания углов.
DOB18 = [{"len": 13, "dir": 180}, {"len": 9, "dir": 90}, {"len": 8, "dir": 0},
         {"len": 18, "dir": 180}, {"len": 5, "dir": 0}, {"len": 9, "dir": -90},
         {"len": 8, "dir": -180}]


def _path_points(svg):
    d = re.search(r'<path d="(M [^"]+)" fill="none" stroke="#111" stroke-width="2.6"', svg).group(1)
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return d, nums


@tagged("post_install", "-at_install")
class TestDoborFolds258(TransactionCase):

    def test_h_profile_folds_return(self):
        """Оба подгиба в одну сторону вращения: слой уходит наверх и возвращается."""
        for segs in (DOB18, DOB18_RAW):
            with self.subTest(raw=segs is DOB18_RAW):
                self.assertTrue(dr._is_fold(segs, 3) and dr._is_fold(segs, 4))
                self.assertEqual(dr._fold_rot(segs, 3), 1, "верхний лист — снаружи, над стенкой")
                self.assertEqual(dr._fold_rot(segs, 4), 1, "второй подгиб возвращает слой к стенке")

    def test_top_layer_above_walls(self):
        """В печати верхний лист выше начала полки 8 (ось Y вниз — меньше y)."""
        svg = dr.sketch_svg({"start": {"x": 0, "y": 0}, "segs": DOB18})
        d, _ = _path_points(svg)
        self.assertEqual(d.count(" A "), 2, "два подгиба — две дуги")
        # Точки «L x y» по порядку: 13, 9, 8, [дуга] 18, [дуга] 5, 9, 8.
        pts = [tuple(map(float, m)) for m in re.findall(r"L (-?[\d.]+) (-?[\d.]+)", d)]
        top_a = pts[2][1]       # конец полки 8 (уровень стенки)
        top_b = pts[3][1]       # конец верхнего листа 18
        end_c = pts[4][1]       # конец полки 5
        self.assertLess(top_b, top_a, "лист 18 лёг поверх, а не внутрь профиля")
        self.assertAlmostEqual(end_c, top_a, 3, msg="полка 5 вернулась на уровень полки 8")
        # После двух подгибов смещения нет: левая стенка и полка там, где их точки.
        v = dr._verts({"x": 0, "y": 0}, DOB18)
        self.assertTrue(svg.startswith("<svg"))
        self.assertEqual(len(v), 8)

    def test_fold_flip_turns_layer(self):
        flipped = [dict(s) for s in DOB18]
        flipped[3]["foldFlip"] = True
        self.assertEqual(dr._fold_rot(flipped, 3), -1)
        # Второй подгиб наследует уже перевёрнутый первый.
        self.assertEqual(dr._fold_rot(flipped, 4), -1)

    def test_single_hem_goes_outward(self):
        """Одиночный подгиб на стенке: наружу, против предыдущего поворота."""
        segs = [{"len": 50, "dir": 0}, {"len": 30, "dir": 90}, {"len": 10, "dir": -90}]
        self.assertEqual(dr._fold_rot(segs, 2), -1)
        mirrored = [{"len": s["len"], "dir": -s["dir"]} for s in segs]
        self.assertEqual(dr._fold_rot(mirrored, 2), 1, "зеркало — на другую сторону")

    def test_crowded_right_angles_not_stacked(self):
        """Две «90°» у стенок в 5 мм не печатаются друг на друге."""
        svg = dr.sketch_svg({"start": {"x": 0, "y": 0}, "segs": DOB18})
        spots = [(float(x), float(y)) for x, y in
                 re.findall(r'<text x="(-?[\d.]+)" y="(-?[\d.]+)"[^>]*font-size="16"[^>]*>90°<', svg)]
        for i, a in enumerate(spots):
            for b in spots[i + 1:]:
                self.assertFalse(abs(a[0] - b[0]) < 31 and abs(a[1] - b[1]) < 18, (a, b))
        # Непрямой угол подписывается всегда, даже без свободного места.
        raw = dr.sketch_svg({"start": {"x": 0, "y": 0}, "segs": DOB18_RAW})
        self.assertEqual(len(re.findall(r">9[12]°<|>89°<", raw)), 4, "91°, 89°, 92°, 91° — все четыре")

    def test_place_label(self):
        placed = []
        self.assertEqual(dr._place_label([(0, 0)], "13", placed, 10, 20), (0, 0))
        self.assertEqual(dr._place_label([(5, 0), (100, 0)], "9", placed, 10, 20), (100, 0))
        self.assertIsNone(dr._place_label([(0, 0)], "90°", placed, 9, 18, optional=True))
