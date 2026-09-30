# -*- coding: utf-8 -*-
"""Строка денег расчёта (разбор UX, шаг 31) — формат без базы.

Обычный unittest: tools/money_text.py — чистые функции, тест гоняется голым
питоном до всякого деплоя:

    python3 experiments/odoo/addons/pmk_deal/tests/test_money_text.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags) — те же
строки через модель сделки проверяет test_deal_money.py.

Эталон — сделка №12 и СМ-00024 боевой базы (30.09.2026): 50 938,926 кг,
цена клиенту 9 500 000, металл к закупке 3 429 021,97, маржа 63,9 %,
позиций без цены 1.
"""

import unittest

try:
    # Внутри Odoo — как odoo.addons.pmk_deal.tools.money_text.
    from ..tools import money_text
except (ImportError, ValueError):
    # Голым питоном — как соседний пакет.
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import money_text

NB = " "


def plain(text):
    """Для сравнения глазами: неразрывный пробел → обычный."""
    return text.replace(NB, " ")


class TestMoneyText(unittest.TestCase):

    def test_deal_line_matches_the_owner_example(self):
        line = money_text.spec_line("СМ-00024", 50938.926, 9500000.0, 3429021.97, 63.9)
        self.assertEqual(
            plain(line),
            "СМ-00024 · 50,9 т · цена 9 500 000 ₽ · металл 3 429 022 ₽ · маржа 63,9 %")

    def test_card_line_matches_the_owner_example(self):
        self.assertEqual(
            plain(money_text.card_line(50938.926, 9500000.0, 63.9)),
            "50,9 т · 9,5 млн ₽ · маржа 64 %")

    def test_line_breaks_only_between_parts(self):
        """Внутри числа и между числом и единицей переноса нет."""
        line = money_text.spec_line("СМ-00024", 50938.926, 9500000.0, 3429021.97, 63.9)
        parts = line.split(money_text.SEP)
        self.assertEqual(len(parts), 5)
        for part in parts[1:]:
            # «цена 9 500 000 ₽»: обычный пробел — только после слова.
            words = part.split(" ")
            self.assertLessEqual(len(words), 2, repr(part))
        self.assertNotIn(" ", parts[0], "Номер СМ- одним куском.")

    def test_without_customer_price_no_margin(self):
        """Цена не назначена — маржи нет (а не «0 %» или «−100 %»)."""
        line = plain(money_text.spec_line("СМ-00016", 4720.172, 0.0, 0.0, 0.0))
        self.assertEqual(line, "СМ-00016 · 4,7 т · цена не назначена · металл 0 ₽")
        self.assertNotIn("маржа", line)
        self.assertEqual(plain(money_text.card_line(4720.172, 0.0, 0.0)),
                         "4,7 т · цена не назначена")

    def test_short_amounts(self):
        cases = [
            (9500000, "9,5 млн ₽"),
            (12000000, "12 млн ₽"),
            (123456789, "123 млн ₽"),
            (54000, "54 тыс ₽"),
            (1500, "1,5 тыс ₽"),
            (950, "950 ₽"),
            (0, "0 ₽"),
        ]
        for amount, expected in cases:
            with self.subTest(amount=amount):
                self.assertEqual(plain(money_text.rub_short(amount)), expected)

    def test_unit_is_chosen_after_rounding(self):
        """Цена КП около миллиона — частый случай: «1 млн ₽», не «1000 тыс ₽»."""
        cases = [
            (999500, "1 млн ₽"),
            (999960, "1 млн ₽"),
            (999499, "999 тыс ₽"),
            (99960, "100 тыс ₽"),
            (99940, "99,9 тыс ₽"),
            (999.6, "1 тыс ₽"),
            (999.4, "999 ₽"),
            (-999500, "-1 млн ₽"),
            (999999999, "1 млрд ₽"),
            (2500000000, "2,5 млрд ₽"),
        ]
        for amount, expected in cases:
            with self.subTest(amount=amount):
                self.assertEqual(plain(money_text.rub_short(amount)), expected)

    def test_weight_unit_is_chosen_after_rounding(self):
        self.assertEqual(plain(money_text.weight(999.6)), "1,0 т")
        self.assertEqual(plain(money_text.weight(999.4)), "999 кг")
        self.assertEqual(plain(money_text.weight(9.96)), "10 кг")
        self.assertEqual(plain(money_text.weight(9.94)), "9,9 кг")

    def test_rounding_is_human(self):
        """0,5 — вверх, как считает человек (round() Python — к чётному)."""
        self.assertEqual(plain(money_text.rub(0.5)), "1 ₽")
        self.assertEqual(plain(money_text.rub(2.5)), "3 ₽")
        self.assertEqual(plain(money_text.pct(62.5, 0)), "63 %")
        self.assertEqual(plain(money_text.pct(63.86, 1)), "63,9 %")
        self.assertEqual(plain(money_text.pct(64.0, 1)), "64 %")
        self.assertEqual(plain(money_text.rub(-6660.37)), "-6 660 ₽")

    def test_weight_like_the_calculator(self):
        self.assertEqual(plain(money_text.weight(50938.926)), "50,9 т")
        self.assertEqual(plain(money_text.weight(442.428)), "442 кг")
        self.assertEqual(plain(money_text.weight(0.4)), "0,4 кг")
        self.assertEqual(plain(money_text.weight(0)), "0 кг")

    def test_no_price_label(self):
        self.assertEqual(money_text.no_price_label(0), "")
        self.assertEqual(money_text.no_price_label(1), "без цены: 1")
        self.assertEqual(money_text.no_price_label(6), "без цены: 6")


if __name__ == "__main__":
    unittest.main()
