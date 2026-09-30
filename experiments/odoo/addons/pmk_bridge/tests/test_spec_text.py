# -*- coding: utf-8 -*-
"""Подписи формы расчёта (разбор UX, шаг 32) — формат без базы.

Обычный unittest: tools/spec_text.py — чистые функции, тест гоняется голым
питоном до всякого деплоя:

    python3 experiments/odoo/addons/pmk_bridge/tests/test_spec_text.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags) — те же
строки через модель расчёта проверяет test_spec_form.py.

Эталон — СМ-00024 боевой базы (30.09.2026): прайсы от 16.06 и 21.09,
«С 16.06: +276 198 ₽ (+8,8 %)» — пример из документа разбора.
"""

import datetime
import unittest

try:
    # Внутри Odoo — как odoo.addons.pmk_bridge.tools.spec_text.
    from ..tools import spec_text
except (ImportError, ValueError):
    # Голым питоном — как соседний пакет.
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import spec_text

NB = " "
D = datetime.date


def plain(text):
    """Для сравнения глазами: неразрывный пробел → обычный."""
    return text.replace(NB, " ") if text else text


class TestCompareSummary(unittest.TestCase):

    def test_owner_example(self):
        self.assertEqual(
            plain(spec_text.compare_summary(276198.4, 8.83, D(2026, 6, 16), base_year=2026)),
            "С 16.06: +276 198 ₽ (+8,8 %)")

    def test_cheaper_uses_typographic_minus(self):
        text = spec_text.compare_summary(-1500.5, -2.04, D(2026, 6, 16), base_year=2026)
        self.assertEqual(plain(text), "С 16.06: −1 501 ₽ (−2 %)")
        self.assertNotIn("-", text, "Минус — U+2212, не дефис.")

    def test_no_change(self):
        self.assertEqual(
            spec_text.compare_summary(0.3, 0.0, D(2026, 6, 16), base_year=2026),
            "С 16.06: без изменений")

    def test_tiny_share_is_not_zero_percent(self):
        self.assertEqual(
            plain(spec_text.compare_summary(450.0, 0.01, D(2026, 6, 16), base_year=2026)),
            "С 16.06: +450 ₽ (меньше 0,1 %)")

    def test_lost_positions_are_named(self):
        self.assertEqual(
            plain(spec_text.compare_summary(-900.0, -5.0, D(2026, 6, 16), lost=2, base_year=2026)),
            "С 16.06: −900 ₽ (−5 %) · выпало из прайса: 2 поз.")

    def test_other_year_keeps_year(self):
        self.assertEqual(
            plain(spec_text.compare_summary(100.0, 10.0, D(2025, 12, 1), base_year=2026)),
            "С 01.12.2025: +100 ₽ (+10 %)")

    def test_nothing_to_compare(self):
        self.assertFalse(spec_text.compare_summary(0.0, 0.0, False))

    def test_numbers_do_not_break(self):
        text = spec_text.compare_summary(276198.4, 8.83, D(2026, 6, 16), base_year=2026)
        self.assertIn("276" + NB + "198" + NB + "₽", text)
        self.assertIn("8,8" + NB + "%", text)

    # ─── Прайс сравнения новее цен расчёта (доводка шага 32) ─────────────
    def test_later_price_is_not_since(self):
        """Расчёт на 17.09, сравниваем со свежим 21.09: не «с 21.09 −…»."""
        text = plain(spec_text.compare_summary(
            100.0, 10.0, D(2026, 9, 21), base_year=2026, later=True))
        self.assertEqual(text, "По прайсу от 21.09 стало бы: +100 ₽ (+10 %)")
        self.assertFalse(text.startswith("С "))

    def test_later_no_change_and_lost(self):
        self.assertEqual(
            spec_text.compare_summary(0.1, 0.0, D(2026, 9, 21), base_year=2026, later=True),
            "По прайсу от 21.09: без изменений")
        self.assertEqual(
            plain(spec_text.compare_summary(50.0, 5.0, D(2026, 9, 21), lost=1,
                                            base_year=2026, later=True)),
            "По прайсу от 21.09 стало бы: +50 ₽ (+5 %) · выпало из прайса: 1 поз.")

    def test_compare_later(self):
        self.assertTrue(spec_text.compare_later(D(2026, 9, 21), D(2026, 9, 17)))
        self.assertFalse(spec_text.compare_later(D(2026, 6, 16), D(2026, 9, 17)))
        self.assertFalse(spec_text.compare_later(D(2026, 9, 17), D(2026, 9, 17)),
                         "Та же дата — тот же прайс, не «новее».")
        self.assertFalse(spec_text.compare_later(False, D(2026, 9, 17)))
        self.assertFalse(spec_text.compare_later(D(2026, 9, 21), False))


class TestMetalLabel(unittest.TestCase):
    """«Металл, ₽» изделия: занижено — с оговоркой (доводка шага 32).

    Числа — боевая база 30.09.2026: СМ-00022 «Секция ограждения ОГ-1»
    2 807,72 без 3 позиций, СМ-00016 — 0,00 при 2 позициях без цены.
    """

    def test_complete(self):
        self.assertEqual(plain(spec_text.metal_label(24926.0, 0)), "24 926,00")

    def test_incomplete_is_lower_bound(self):
        self.assertEqual(plain(spec_text.metal_label(2807.72, 3)),
                         "≥ 2 807,72 · без 3 поз.")
        self.assertEqual(plain(spec_text.metal_label(3429021.97, 1)),
                         "≥ 3 429 021,97 · без 1 поз.")

    def test_zero_with_missing_is_not_free(self):
        self.assertEqual(plain(spec_text.metal_label(0.0, 2)), "нет в прайсах: 2 поз.")

    def test_nothing_to_count(self):
        self.assertEqual(spec_text.metal_label(0.0, 0), "—")
        self.assertEqual(spec_text.metal_label(False, False), "—")

    def test_numbers_do_not_break(self):
        text = spec_text.metal_label(3429021.97, 1)
        self.assertIn("3" + NB + "429" + NB + "021,97", text)
        self.assertIn("≥" + NB, text)
        self.assertIn("1" + NB + "поз.", text)

    def test_money2(self):
        self.assertEqual(plain(spec_text.money2(1100)), "1 100,00")
        self.assertEqual(plain(spec_text.money2(0.005)), "0,01")
        self.assertEqual(spec_text.money2(-5), "−5,00")


class TestStaleLabel(unittest.TestCase):

    def test_words_instead_of_bang(self):
        self.assertEqual(spec_text.stale_label(D(2026, 9, 21), D(2026, 9, 17)),
                         "есть прайс от 21.09")

    def test_year_only_when_differs(self):
        self.assertEqual(spec_text.stale_label(D(2027, 1, 12), D(2026, 12, 20)),
                         "есть прайс от 12.01.2027")

    def test_empty(self):
        self.assertFalse(spec_text.stale_label(False, D(2026, 9, 17)))


class TestKpSkip(unittest.TestCase):

    def test_one(self):
        self.assertEqual(plain(spec_text.kp_skip_text(["тест"])),
                         "В КП не попадут без цены: 1 изделие — «тест»")

    def test_plural_and_rest(self):
        text = plain(spec_text.kp_skip_text(["А", "Б", "В", "Г", "Д"]))
        self.assertEqual(
            text, "В КП не попадут без цены: 5 изделий — «А», «Б», «В» и ещё 2")
        self.assertEqual(
            plain(spec_text.kp_skip_text(["А", "Б"])),
            "В КП не попадут без цены: 2 изделия — «А», «Б»")
        self.assertIn("21 изделие", plain(spec_text.kp_skip_text(["x"] * 21)))
        self.assertIn("11 изделий", plain(spec_text.kp_skip_text(["x"] * 11)))

    def test_nothing_skipped(self):
        self.assertFalse(spec_text.kp_skip_text([]))

    def test_nameless(self):
        self.assertIn("«без названия»", spec_text.kp_skip_text([False]))


class TestPerTon(unittest.TestCase):

    def test_sheet_price(self):
        # Лист 10 мм 1500×6000: 51 395,25 ₽ за лист, 706,5 кг → 72 746 ₽/т
        # (СМ-00024, price_ton боевой базы).
        self.assertEqual(round(spec_text.per_ton(51395.25, 706.5)), 72746)

    def test_zero_mass_is_zero_not_error(self):
        """Мина листа 1500×6000: масса обнулилась — ноль, а не деление на ноль."""
        self.assertEqual(spec_text.per_ton(51395.25, 0.0), 0.0)
        self.assertEqual(spec_text.per_ton(0.0, 706.5), 0.0)


if __name__ == "__main__":
    unittest.main()
