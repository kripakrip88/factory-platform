# -*- coding: utf-8 -*-
"""Совместная раскладка листа (разбор UX, шаг З-13) — без базы.

Обычный unittest: sheeting.py — чистые функции, тест гоняется голым питоном:

    python3 experiments/odoo/addons/pmk_calc/tests/test_sheet_group.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags) — поля
групп на расчёте, вкладку и заявку на металл проверяют test_step_z13.py
(pmk_calc) и test_step_z13.py (pmk_tech).

Главный пример — прогон Кытмановой 09.10 (боевая база, СМ-00037 / СМ-00038):
лист гладкий 3 мм 1500×6000, П-полоса 120×3000 ×617 (24 в листе, 26 листов)
и Z-полоса 560×3000 ×265 (4 в листе, 67 листов, обрезок 380 мм на каждом).
Раздельно 93 листа, вместе — 76.
"""

import random
import unittest

try:
    from ..models import sheeting
except (ImportError, ValueError):
    # Голым питоном: файл грузим напрямую — пакет models тянет odoo.
    import importlib.util
    import os
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "models", "sheeting.py")
    _spec = importlib.util.spec_from_file_location("pmk_sheeting", _path)
    sheeting = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sheeting)

W, L = 1500.0, 6000.0
KERF = sheeting.DEFAULT_KERF_MM
TOL = sheeting.DEFAULT_TOLERANCE_MM
KYTMANOVA = [("P", 120.0, 3000.0, 617), ("Z", 560.0, 3000.0, 265)]


class TestSheetGroup(unittest.TestCase):

    def check_placements(self, parts, packed, sheet_w=W, sheet_l=L):
        """Реальная укладка: каждая деталь на месте, ни одна не вылезает за
        лист (кроме допуска ряда), ни одна не налезает на соседнюю с учётом
        реза, штук ровно столько, сколько нужно, площадь ≤ площади листов."""
        placed = list(sheeting.iter_placements(sheet_w, sheet_l, packed, KERF))
        need = {key: qty for key, _a, _b, qty in parts}
        got = {}
        for _no, key, _x, _y, _w, _l in placed:
            got[key] = got.get(key, 0) + 1
        self.assertEqual(got, {key: qty for key, qty in need.items() if qty > 0})
        sizes = {key: sorted((a, b)) for key, a, b, _qty in parts}
        by_sheet = {}
        for number, key, x, y, w, l in placed:
            self.assertEqual(sorted((w, l)), sizes[key], "Деталь легла своим размером.")
            self.assertGreaterEqual(x, -1e-6)
            self.assertGreaterEqual(y, -1e-6)
            self.assertLessEqual(x + w, sheet_w + TOL + 1e-6, "Вылезла за ширину листа.")
            self.assertLessEqual(y + l, sheet_l + TOL + 1e-6, "Вылезла за длину листа.")
            by_sheet.setdefault(number, []).append((x, y, w, l))
        self.assertEqual(len(by_sheet), packed["sheets"])
        for rects in by_sheet.values():
            for index, (x1, y1, w1, l1) in enumerate(rects):
                for x2, y2, w2, l2 in rects[index + 1:]:
                    apart = (x1 + w1 + KERF <= x2 + 1e-6 or x2 + w2 + KERF <= x1 + 1e-6
                             or y1 + l1 + KERF <= y2 + 1e-6 or y2 + l2 + KERF <= y1 + 1e-6)
                    self.assertTrue(apart, "Детали налезли друг на друга (рез учтён).")
        area = sum(a * b * qty for _key, a, b, qty in parts)
        self.assertLessEqual(area, packed["sheets"] * sheet_w * sheet_l)

    # ─── Прогон Кытмановой ───────────────────────────────────────────────
    def test_kytmanova_joint(self):
        plan = sheeting.plan_group(W, L, KYTMANOVA)
        self.assertEqual(plan["sheets_separate"], 93, "Раздельно — 26 + 67.")
        self.assertEqual(plan["mode"], "joint")
        self.assertLessEqual(plan["sheets"], 80)
        self.assertEqual(plan["sheets"], 76)
        self.assertGreater(plan["utilization_pct"], 95.0)
        lines = plan["lines"]
        self.assertEqual(lines["P"]["sheets"] + lines["Z"]["sheets"], 76,
                         "Доли строк складываются в листы группы — без задвоения.")
        # «В листе» и «Схема» строки — свои, «если резать отдельно».
        self.assertEqual(lines["P"]["per_sheet"], 24)
        self.assertEqual(lines["Z"]["per_sheet"], 4)
        self.assertEqual(lines["Z"]["state"], "ok")

    def test_kytmanova_real_layout(self):
        packed = sheeting.pack_group(W, L, KYTMANOVA)
        self.assertEqual(packed["sheets"], 76)
        self.check_placements(KYTMANOVA, packed)

    def test_scheme_words(self):
        plan = sheeting.plan_group(W, L, KYTMANOVA)
        text = sheeting.group_scheme_text(plan["patterns"], {"P": "120×3000", "Z": "560×3000"})
        self.assertTrue(text.startswith("66 листов: 120×3000 — 6, 560×3000 — 4"), text)
        self.assertIn("ещё 1 вариант", text)
        self.assertEqual(sheeting.part_label(120.5, 3000.0), "120,5×3000")

    # ─── Никогда не хуже прежнего ─────────────────────────────────────────
    def test_single_part_is_plan_sheets(self):
        """Одна деталь в группе — тот же plan_sheets один в один."""
        for a, b, qty in ((500, 500, 37), (90, 460, 1000), (1500, 1000, 7),
                          (1500, 6000, 3), (1600, 7000, 2), (0, 200, 5), (120, 210, 0)):
            with self.subTest(size="%sx%s" % (a, b), qty=qty):
                plan = sheeting.plan_group(W, L, [("x", float(a), float(b), qty)])
                single = sheeting.plan_sheets(W, L, float(a), float(b), qty)
                self.assertEqual(plan["mode"], "separate")
                self.assertEqual(plan["sheets"], single["sheets"])
                self.assertEqual(plan["lines"]["x"], dict(single, joint=False))

    def test_never_worse_than_separate(self):
        rng = random.Random(1309)
        for _round in range(300):
            parts = [(index, float(rng.choice((40, 90, 120, 250, 300, 380, 560, 740, 1400))),
                      float(rng.choice((90, 210, 460, 1000, 2500, 3000, 5900))),
                      rng.randint(0, 400)) for index in range(rng.randint(2, 6))]
            sheet_w, sheet_l = rng.choice(((1500.0, 6000.0), (1500.0, 3000.0), (1000.0, 4000.0)))
            plan = sheeting.plan_group(sheet_w, sheet_l, parts)
            self.assertLessEqual(plan["sheets"], plan["sheets_separate"], parts)
            self.assertEqual(sum(line["sheets"] for line in plan["lines"].values()),
                             plan["sheets"], parts)
            if plan["mode"] == "joint":
                self.assertLess(plan["sheets"], plan["sheets_separate"])

    def test_random_layouts_are_real(self):
        rng = random.Random(56)
        for _round in range(60):
            parts = [(index, float(rng.choice((40, 120, 250, 380, 560, 740))),
                      float(rng.choice((90, 460, 1000, 3000))),
                      rng.randint(1, 60)) for index in range(rng.randint(2, 4))]
            packed = sheeting.pack_group(W, L, parts)
            self.check_placements(parts, packed)

    # ─── Детали без своей раскладки ───────────────────────────────────────
    def test_too_big_does_not_break_group(self):
        """Деталь «больше листа» не роняет группу: листов не даёт, остальные
        раскладываются вместе."""
        parts = KYTMANOVA + [("big", 1600.0, 7000.0, 3), ("nosize", 0.0, 100.0, 4)]
        plan = sheeting.plan_group(W, L, parts)
        self.assertEqual(plan["sheets"], 76)
        self.assertEqual(plan["lines"]["big"]["state"], "too_big")
        self.assertEqual(plan["lines"]["big"]["sheets"], 0)
        self.assertEqual(plan["lines"]["nosize"]["state"], "no_size")

    def test_exact_sheet_counts_as_before(self):
        """Деталь в размер листа — по листу на штуку и в группе."""
        parts = KYTMANOVA + [("exact", 1500.0, 6000.0, 2)]
        plan = sheeting.plan_group(W, L, parts)
        self.assertEqual(plan["sheets_separate"], 95)
        self.assertEqual(plan["sheets"], 78)
        self.assertEqual(plan["lines"]["exact"]["sheets"], 2)
        self.assertEqual(plan["lines"]["exact"]["state"], "exact")
        # «Вместе» — только те, кто лёг на общие листы (доработка З-13).
        self.assertTrue(plan["lines"]["P"]["joint"])
        self.assertTrue(plan["lines"]["Z"]["joint"])
        self.assertFalse(plan["lines"]["exact"]["joint"], "В размер листа — свои листы.")

    def test_joint_flag_only_for_packed(self):
        """Деталь «больше листа» и без габарита — не «вместе»."""
        parts = KYTMANOVA + [("big", 1600.0, 7000.0, 3), ("nosize", 0.0, 100.0, 4)]
        lines = sheeting.plan_group(W, L, parts)["lines"]
        self.assertEqual({key: line["joint"] for key, line in lines.items()},
                         {"P": True, "Z": True, "big": False, "nosize": False})

    def test_joint_false_is_separate(self):
        """joint=False (детали без выбранного листа) — только раздельно."""
        plan = sheeting.plan_group(W, L, KYTMANOVA, joint=False)
        self.assertEqual((plan["mode"], plan["sheets"], plan["sheets_separate"]),
                         ("separate", 93, 93))
        self.assertFalse(any(line["joint"] for line in plan["lines"].values()))

    def test_remainders_variant(self):
        """Полные листы каждой детали — отдельно, остатки — вместе: две
        детали с хвостами по полтора листа дают один общий хвостовой лист."""
        per = sheeting.fit_sheet(W, L, 500.0, 500.0)[0]
        parts = [("a", 500.0, 500.0, per * 3 + 5), ("b", 500.0, 500.0, per * 2 + 7)]
        plan = sheeting.plan_group(W, L, parts)
        self.assertEqual(plan["sheets_separate"], 7)
        self.assertEqual(plan["sheets"], 6)
        self.assertEqual(plan["mode"], "joint")

    def test_shares(self):
        shares = sheeting._shares(76, {"P": 222.12, "Z": 445.2})
        self.assertEqual(sum(shares.values()), 76)
        self.assertEqual(shares, {"P": 25, "Z": 51})
        self.assertEqual(sheeting._shares(1, {"a": 1.0, "b": 1.0, "c": 1.0}), {"a": 1, "b": 0, "c": 0})
        self.assertEqual(sheeting._shares(0, {"a": 1.0}), {"a": 0})

    def test_big_quantity_is_fast(self):
        """36 388 заготовок (СМ-00039) — без заметной задержки."""
        import time
        start = time.time()
        plan = sheeting.plan_group(W, L, [("a", 100.0, 100.0, 36388), ("b", 90.0, 460.0, 5000)])
        self.assertLess(time.time() - start, 2.0)
        self.assertLessEqual(plan["sheets"], plan["sheets_separate"])


if __name__ == "__main__":
    unittest.main()
