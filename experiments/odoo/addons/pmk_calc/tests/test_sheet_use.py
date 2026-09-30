# -*- coding: utf-8 -*-
"""Использование листа на вкладке «Раскладка» (разбор UX, шаг 32) — без базы.

Обычный unittest: sheeting.py — чистые функции, тест гоняется голым питоном:

    python3 experiments/odoo/addons/pmk_calc/tests/test_sheet_use.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags) — поля
строки и запись в историю проверяет test_spec_form.py.

Числа — из раскладок боевой базы 30.09.2026: СМ-00024 «Лестницы −6» 4,7 %
(лист 6 мм ради 20 кг), «Колонны −8» 33,7 %, «Колонны −10» 50,9 %,
СМ-00023 — 56,0 %.
"""

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

NB = " "


def plain(text):
    return text.replace(NB, " ") if text else text


class TestSheetUse(unittest.TestCase):

    def label(self, pct, state="ok"):
        text, level = sheeting.sheet_use_label(pct, state)
        return plain(text), level

    def test_owner_thresholds(self):
        self.assertEqual(sheeting.SHEET_USE_LOW_PCT, 50.0)
        self.assertEqual(sheeting.SHEET_USE_BAD_PCT, 20.0)

    def test_live_numbers(self):
        self.assertEqual(self.label(4.7), ("4,7 % · очень мало", "bad"))
        self.assertEqual(self.label(33.7), ("33,7 % · мало", "low"))
        self.assertEqual(self.label(50.9), ("50,9 %", "ok"))
        self.assertEqual(self.label(56.0), ("56 %", "ok"))

    def test_edges(self):
        self.assertEqual(self.label(50.0)[1], "ok")
        self.assertEqual(self.label(49.9)[1], "low")
        self.assertEqual(self.label(20.0)[1], "low")
        self.assertEqual(self.label(19.9)[1], "bad")

    def test_exact_sheet_counts(self):
        """«Деталь в размер листа» — тоже посчитанная раскладка."""
        self.assertEqual(self.label(96.3, "exact"), ("96,3 %", "ok"))

    def test_not_counted_has_no_label(self):
        for state in ("none", "no_size", "no_qty", "too_big", False):
            with self.subTest(state=state):
                self.assertEqual(sheeting.sheet_use_label(0.0, state), (False, "none"))

    def test_percent_does_not_break(self):
        text, _level = sheeting.sheet_use_label(4.7, "ok")
        self.assertIn("4,7" + NB + "%", text)


if __name__ == "__main__":
    unittest.main()
