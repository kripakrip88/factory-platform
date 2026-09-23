# -*- coding: utf-8 -*-
"""Проверки черновой раскладки листа.

Числа взяты из живых данных стенда, а не выдуманы: размеры заготовок — из
спецификаций СМ-00015…СМ-00023, габариты листа — те три, что заведены
характеристикой номенклатуры.

Считаем вручную и сверяем: формула укладки ошибается незаметно, на одну
заготовку в ряду, и такая ошибка сразу уходит в деньги.
"""

from odoo.tests import TransactionCase

from ..models.sheeting import fit_sheet, plan_sheets

W, L = 1500.0, 6000.0          # ходовой лист
KERF = 0.2                      # рез лазера
EDGE = 0.0                      # кромку не оставляем (решение владельца)


class TestSheeting(TransactionCase):

    def test_ряд_считает_резы_между_заготовками(self):
        """В ряду из n заготовок резов n−1, а не n.

        Заготовка 500 мм в листе 1500: помещается ровно три штуки, между ними
        два реза по 0,2 мм. Формула, которая закладывает рез после каждой
        заготовки, даёт две — и лист покупается вдвое чаще.
        """
        count, _scheme, state = fit_sheet(W, L, 500.0, 500.0, KERF, EDGE)
        self.assertEqual(state, "ok")
        # 3 по ширине × 12 по длине
        self.assertEqual(count, 36)

    def test_заготовка_в_размер_листа(self):
        """Деталь шириной ровно в лист режет прокатный стан, а не наш станок.

        Без правила «в размер по оси» заготовка 1500×1000 из листа 1500×6000
        дала бы ноль штук: на рез по ширине не осталось бы миллиметров.
        """
        count, _scheme, state = fit_sheet(W, L, 1500.0, 1000.0, KERF, EDGE)
        self.assertEqual(state, "ok")
        self.assertEqual(count, 6)

    def test_поворот_заготовки_считается(self):
        """Заготовка 1400×200: поперёк листа влезает одна, вдоль — семь.

        Если считать только один поворот, разница получается в разы.
        """
        count, scheme, state = fit_sheet(W, L, 1400.0, 200.0, KERF, EDGE)
        self.assertEqual(state, "ok")
        self.assertGreaterEqual(count, 30)
        self.assertIn("×", scheme)

    def test_заготовка_больше_листа(self):
        count, _scheme, state = fit_sheet(W, L, 1600.0, 7000.0, KERF, EDGE)
        self.assertEqual(state, "too_big")
        self.assertEqual(count, 0)

    def test_габарит_не_задан(self):
        count, _scheme, state = fit_sheet(W, L, 0.0, 200.0, KERF, EDGE)
        self.assertEqual(state, "no_size")
        self.assertEqual(count, 0)

    def test_смешанная_укладка_не_хуже_рядов(self):
        """Полоса из остатка добавляет заготовки, но никогда не отнимает."""
        for a, b in ((90.0, 460.0), (250.0, 250.0), (120.0, 210.0), (300.0, 300.0)):
            rows, _s1, _st1 = fit_sheet(W, L, a, b, KERF, EDGE, mixed=False)
            mixed, _s2, _st2 = fit_sheet(W, L, a, b, KERF, EDGE, mixed=True)
            self.assertGreaterEqual(
                mixed, rows,
                "смешанная укладка проиграла рядам на заготовке %sx%s" % (a, b))

    def test_листов_под_количество(self):
        """Заготовка 120×210, нужно 10 штук — хватает одного листа.

        Живая строка из СМ-00023. В лист их влезает много, поэтому лист один,
        а использование низкое: купили целый, взяли малую часть.
        """
        plan = plan_sheets(W, L, 120.0, 210.0, 10, kerf_mm=KERF, edge_mm=EDGE)
        self.assertEqual(plan["state"], "ok")
        self.assertEqual(plan["sheets"], 1)
        self.assertGreater(plan["per_sheet"], 10)
        # 10 заготовок по 0,0252 м² = 0,252 м² из 9 м² листа
        self.assertAlmostEqual(plan["utilization_pct"], 2.8, delta=0.1)

    def test_использование_растёт_с_количеством(self):
        """Та же заготовка, но на полный лист — использование под сотню.

        Это и есть ответ на разброс «от 50 до 97%»: доля зависит не от
        материала, а от того, сколько заготовок заказано.
        """
        per_sheet, _scheme, _state = fit_sheet(W, L, 120.0, 210.0, KERF, EDGE)
        plan = plan_sheets(W, L, 120.0, 210.0, per_sheet, kerf_mm=KERF, edge_mm=EDGE)
        self.assertEqual(plan["sheets"], 1)
        self.assertGreater(plan["utilization_pct"], 90.0)

    def test_второй_лист_считается_целиком(self):
        """Заготовок на лист с небольшим хвостом — покупаем два листа.

        Хвостовой лист и есть главная причина низкого использования: на
        живых лазерных заданиях последний лист партии давал 25% против 65%
        у полных.
        """
        per_sheet, _scheme, _state = fit_sheet(W, L, 500.0, 500.0, KERF, EDGE)
        plan = plan_sheets(W, L, 500.0, 500.0, per_sheet + 1, kerf_mm=KERF, edge_mm=EDGE)
        self.assertEqual(plan["sheets"], 2)
        self.assertLess(plan["utilization_pct"], 60.0)

    def test_нулевое_количество(self):
        plan = plan_sheets(W, L, 120.0, 210.0, 0, kerf_mm=KERF, edge_mm=EDGE)
        self.assertEqual(plan["state"], "no_qty")
        self.assertEqual(plan["sheets"], 0)
