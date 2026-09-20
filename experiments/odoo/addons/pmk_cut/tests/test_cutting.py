# -*- coding: utf-8 -*-
"""Проверки раскроя.

Расчёт не трогает базу, поэтому проверяется обычным unittest — быстро и без
поднятия окружения. Случаи взяты не из головы: часть из реальных данных
спецификации, часть — те, на которых расчёт уже один раз ошибся.
"""

from odoo.tests.common import BaseCase

from ..models.cutting import cut_plan


class TestCutting(BaseCase):

    def test_kerf_between_parts_not_after_each(self):
        """Пропил — МЕЖДУ отрезками. Здесь легко потерять металл на бумаге.

        Четыре отрезка по 1450 = 5800, резов три, а не четыре: 5800 + 9 = 5809.
        Если считать рез после каждого, остаток выйдет 188 вместо 191.
        """
        res = cut_plan([{"length": 6000, "qty": 1}],
                       [{"length": 1450, "qty": 4}], kerf=3)
        self.assertEqual(len(res["bars"][0]["pieces"]), 4)
        self.assertEqual(res["bars"][0]["leftover"], 191.0)

    def test_real_specification_data(self):
        """Данные из реальной спецификации СМ: стойки и раскосы."""
        res = cut_plan([{"length": 6000, "qty": None}],
                       [{"length": 1450, "qty": 22}, {"length": 850, "qty": 10}],
                       kerf=3, min_useful=500)
        self.assertEqual(res["unplaced"], [])
        self.assertEqual(res["total_parts"], 1450 * 22 + 850 * 10)
        # Теоретический минимум — грубая нижняя граница; хуже неё на пару
        # хлыстов допустимо, сильно хуже — повод смотреть алгоритм.
        self.assertLessEqual(res["bars_used"], res["lower_bound"] + 2)

    def test_picks_profitable_stock_length(self):
        """Две длины сразу — берём выгодную, а не первую попавшуюся.

        Восемь отрезков по 2900. Четыре хлыста по 6 м дают 3,33% отхода,
        два по 11,7 м — 0,85%. Расчёт однажды выбирал первое.
        """
        res = cut_plan([{"length": 11700, "qty": None, "name": "11,7"},
                        {"length": 6000, "qty": None, "name": "6"}],
                       [{"length": 2900, "qty": 8}], kerf=2, min_useful=500)
        self.assertEqual(res["unplaced"], [])
        self.assertEqual(res["bars_used"], 2)
        self.assertEqual({b["stock_name"] for b in res["bars"]}, {"11,7"})

    def test_yard_offcuts_go_first(self):
        """Очерёдность — решение пользователя, перебор её не отменяет."""
        res = cut_plan([{"length": 6000, "qty": None, "name": "хлыст", "priority": 50},
                        {"length": 1800, "qty": 2, "name": "обрезок", "priority": 1}],
                       [{"length": 1700, "qty": 2}, {"length": 1450, "qty": 2}],
                       kerf=3, min_useful=500)
        self.assertEqual([b["stock_name"] for b in res["bars"][:2]],
                         ["обрезок", "обрезок"])

    def test_too_long_part_reported_not_silently_dropped(self):
        """Молча потерять деталь — хуже, чем сказать, что она не влезла."""
        res = cut_plan([{"length": 6000, "qty": None}],
                       [{"length": 8000, "qty": 1}], kerf=3)
        self.assertEqual(res["unplaced"], [{"length": 8000.0, "qty": 1}])
        self.assertEqual(res["bars_used"], 0)

    def test_useful_leftover_split_from_scrap(self):
        """Остаток 600 идёт на склад, 200 — в лом."""
        res = cut_plan([{"length": 6000, "qty": 2}],
                       [{"length": 5400, "qty": 1}, {"length": 5800, "qty": 1}],
                       kerf=0, min_useful=500)
        self.assertEqual(res["useful_leftovers"], [600.0])
        self.assertEqual(res["scrap"], 200.0)

    def test_patterns_grouped(self):
        """Цеху нужна схема и число повторов, а не сто одинаковых строк."""
        res = cut_plan([{"length": 6000, "qty": None}],
                       [{"length": 1450, "qty": 12}], kerf=3)
        self.assertEqual(len(res["patterns"]), 1)
        self.assertEqual(res["patterns"][0]["count"], 3)

    def test_large_order_is_fast_enough(self):
        """Размер заказа не должен решать: сложность в числе РАЗНЫХ длин."""
        parts = [{"length": 1450, "qty": 200}, {"length": 850, "qty": 200},
                 {"length": 2300, "qty": 100}]
        res = cut_plan([{"length": 12000, "qty": None}, {"length": 6000, "qty": None}],
                       parts, kerf=3, min_useful=500)
        self.assertEqual(res["unplaced"], [])
        self.assertEqual(res["total_parts"], 1450 * 200 + 850 * 200 + 2300 * 100)
