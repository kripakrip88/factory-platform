# -*- coding: utf-8 -*-
"""Главная производства (16.10.2026): данные, переходы, состав меню «Производства»."""
from odoo.tests import TransactionCase, tagged

from ..models.prod_home import tons


@tagged("post_install", "-at_install")
class TestProdHome(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Home = self.env["pmk.prod.home"]

    def test_tons(self):
        self.assertEqual(tons(12400), "12,4 т")
        self.assertEqual(tons(380), "380 кг")

    def test_dashboard(self):
        data = self.Home.get_dashboard()
        self.assertTrue(data["hello"].startswith(("Доброе", "Добрый")))
        self.assertEqual([s["code"] for s in data["orders"]["stages"]],
                         ["queue", "drawings", "metal", "work", "ready"])
        self.assertEqual(len(data["orders"]["week"]), 7)
        self.assertIn("rows", data["laser"])
        self.assertIsNotNone(data["calc"]["dobor"])
        for block in ("orders", "metal", "laser"):
            for key in ("_hot", "_late", "_new"):
                self.assertNotIn(key, data.get(block) or {}, "служебное поле не уходит в браузер")

    def test_open_blocks(self):
        for key in ("orders", "overdue", "laser", "calc_dobor", "calc_vent", "calc_tech"):
            with self.subTest(key=key):
                self.assertTrue(self.Home.open_block(key))
        stage = self.Home.open_block("stage", "drawings")
        self.assertIn(("stage_id.pmk_order_stage", "=", "drawings"), stage["domain"])
        new = self.Home.open_block("new_dobor")
        self.assertEqual(new["views"][0][1], "form")
        self.assertFalse(self.Home.open_block("nothing"))

    def test_menu(self):
        """«Производство» — всем; лазер и калькуляторы — внутри; штатное производство — под галочкой."""
        prod = self.env.ref("pmk_theme.menu_pmk_production")
        self.assertFalse(prod.group_ids, "раздел виден всем")
        for xmlid in ("pmk_laser.menu_pmk_laser", "pmk_calc.menu_pmk_calc", "pmk_cut.menu_pmk_cut",
                      "pmk_calc.menu_pmk_calc_reference", "pmk_prod_home.menu_prod_home"):
            with self.subTest(menu=xmlid):
                self.assertEqual(self.env.ref(xmlid).parent_id, prod)
        first = prod.child_id.sorted("sequence")[0]
        self.assertEqual(first, self.env.ref("pmk_prod_home.menu_prod_home"))
        group = self.env.ref("pmk_theme.group_pmk_production")
        self.assertIn(group, self.env.ref("pmk_theme.menu_pmk_prod_orders").group_ids)
        # «Заказы в работе» — и в «Продажах» тоже
        self.assertEqual(self.env.ref("pmk_orders.menu_orders_sales").parent_id,
                         self.env.ref("pmk_theme.menu_pmk_sales"))
