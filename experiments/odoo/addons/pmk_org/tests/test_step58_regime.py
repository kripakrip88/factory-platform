# -*- coding: utf-8 -*-
"""Налоговый режим на дату (разбор UX, шаг 58) — без базы.

    python3 experiments/odoo/addons/pmk_org/tests/test_step58_regime.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags) — то же
через модель проверяет test_step58_org.py.
"""

import datetime
import unittest

try:
    from ..tools import regime as rg
except (ImportError, ValueError):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import regime as rg

D = datetime.date
ROWS = [(D(2026, 1, 1), "vat22"), (D(2027, 1, 1), "usn0")]


class TestRegimeAt(unittest.TestCase):

    def test_before_and_after_change(self):
        self.assertEqual(rg.regime_at(ROWS, D(2026, 12, 31)), "vat22")
        self.assertEqual(rg.regime_at(ROWS, D(2027, 1, 1)), "usn0", "С даты начала — новый режим.")
        self.assertEqual(rg.regime_at(ROWS, D(2030, 5, 5)), "usn0")

    def test_before_first_row_takes_earliest(self):
        self.assertEqual(rg.regime_at(ROWS, D(2025, 6, 1)), "vat22",
                         "Документ задним числом — по самому раннему режиму, не без налога.")

    def test_order_of_rows_does_not_matter(self):
        self.assertEqual(rg.regime_at(list(reversed(ROWS)), D(2026, 6, 1)), "vat22")

    def test_no_rows(self):
        self.assertIsNone(rg.regime_at([], D(2026, 6, 1)))

    def test_no_date_takes_latest(self):
        self.assertEqual(rg.regime_at(ROWS, None), "usn0")

    def test_today_label(self):
        self.assertEqual(rg.today_label(ROWS, D(2026, 10, 8)), "НДС 22%")
        self.assertEqual(rg.today_label(ROWS, D(2027, 3, 1)), "УСН без НДС")
        self.assertEqual(rg.today_label([(D(2027, 1, 1), "usn0")], D(2026, 10, 8)),
                         "не задан (с 01.01.2027 — УСН без НДС)",
                         "Строка «будет» — не «сегодня»; regime_at её всё равно даст печати.")
        self.assertEqual(rg.regime_at([(D(2027, 1, 1), "usn0")], D(2026, 10, 8)), "usn0")
        self.assertEqual(rg.today_label([], D(2026, 10, 8)), "")

    def test_state(self):
        today = D(2026, 10, 8)
        self.assertEqual(rg.state_of(D(2026, 1, 1), D(2027, 1, 1), today), "current")
        self.assertEqual(rg.state_of(D(2027, 1, 1), None, today), "future")
        self.assertEqual(rg.state_of(D(2025, 1, 1), D(2026, 1, 1), today), "past")

    def test_regimes_and_rates(self):
        self.assertEqual([r for r, _l in rg.REGIMES], ["vat22", "usn0", "usn5", "usn7"])
        self.assertEqual(rg.REGIME_LABELS["usn0"], "УСН без НДС")
        self.assertEqual(rg.RATES, {"vat22": 22.0, "usn0": 0.0, "usn5": 5.0, "usn7": 7.0})
        self.assertTrue(rg.is_usn("usn5"))
        self.assertFalse(rg.is_usn("vat22"))
        names = [rg.TAXES[r][0] for r in rg.RATES]
        self.assertEqual(len(set(names)), 4, "Имена налогов уникальны в компании.")
        self.assertEqual(rg.TAXES["vat22"][0], "НДС 22% (продажа)", "Имя уже заведённого налога.")

    def test_signer_from_name(self):
        self.assertEqual(rg.signer_from_name("ИП Чулков Владислав Витальевич"),
                         "Чулков Владислав Витальевич")
        self.assertEqual(rg.signer_from_name("Индивидуальный предприниматель Иванов И. И."),
                         "Иванов И. И.")
        self.assertEqual(rg.signer_from_name("ООО «Ромашка»"), "ООО «Ромашка»")


if __name__ == "__main__":
    unittest.main()
