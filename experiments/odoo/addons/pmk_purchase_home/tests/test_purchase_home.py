# -*- coding: utf-8 -*-
"""Главная закупок (18.10.2026): данные, маяк свежести прайса, переходы, меню."""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.purchase_home import age_level, money, tons


@tagged("post_install", "-at_install")
class TestPurchaseHome(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Home = self.env["pmk.purchase.home"]

    def test_helpers(self):
        self.assertEqual(tons(6800), "6,8 т")
        self.assertEqual(money(512000), "512 тыс. ₽")
        self.assertEqual(money(1070000), "1,07 млн ₽")
        self.assertEqual([age_level(d) for d in (None, 3, 14, 15, 30, 31)],
                         ["none", "ok", "ok", "warning", "warning", "danger"])

    def test_dashboard(self):
        data = self.Home.get_dashboard()
        self.assertTrue(data["hello"].startswith(("Доброе", "Добрый")))
        self.assertEqual([s["code"] for s in data["requests"]["stages"]],
                         ["draft", "sent", "purchase", "arrived"])
        self.assertIn("rows", data["prices"])
        self.assertEqual([r["key"] for r in data["coverage"]["rows"]], ["profile", "sheet", "fastener"])
        for key in ("_late", "_draft", "_orphan"):
            self.assertNotIn(key, data["requests"], "служебное поле не уходит в браузер")

    def test_price_beacon(self):
        """Маяк: поставщик с прайсом 40-дневной давности — «устарел» и попадает в «Сделать сегодня»."""
        today = fields.Date.context_today(self.Home)
        partner = self.env["res.partner"].create({"name": "Поставщик маяка (тест)", "is_company": True,
                                                  "pmk_price_supplier": True})
        product = self.env["product.template"].create({"name": "Товар маяка (тест)"})
        self.env["product.supplierinfo"].create({"partner_id": partner.id, "product_tmpl_id": product.id,
                                                 "price": 10.0, "date_start": today - timedelta(days=40)})
        partner.invalidate_recordset(["pmk_price_last_date"])
        data = self.Home.get_dashboard()
        row = next((r for r in data["prices"]["rows"] if r["id"] == partner.id), None)
        if row is None:   # в базе больше шести свежих поставщиков — маяк в «ещё»
            self.assertTrue(data["prices"]["more"])
            return
        self.assertEqual(row["level"], "danger")
        self.assertEqual(row["days"], 40)
        self.assertEqual(row["count"], 1)

    def test_request_weight_and_stage(self):
        """Заявка на металл: «Заявка» в стадиях, масса — количество × вес единицы."""
        spec = self.env["pmk.metal.spec"].create({"name": "ТР тест главной закупок"})
        supplier = self.env["res.partner"].create({"name": "Поставщик заявки (тест)", "is_company": True})
        product = self.env["product.product"].create({"name": "Труба тест", "weight": 6.73})
        po = self.env["purchase.order"].create({
            "partner_id": supplier.id, "pmk_tech_spec_id": spec.id,
            "order_line": [(0, 0, {"product_id": product.id, "product_qty": 12.0, "price_unit": 500.0})]})
        self.assertAlmostEqual(self.Home._weight(po), 80.76, places=2)
        data = self.Home.get_dashboard()
        draft = next(s for s in data["requests"]["stages"] if s["code"] == "draft")
        self.assertGreaterEqual(draft["count"], 1)
        self.assertTrue(any(i["kind"] == "po" and i["id"] == po.id for i in data["todo"]),
                        "Неотправленная заявка — в «Сделать сегодня».")

    def test_open_blocks(self):
        for key in ("requests", "suppliers", "prices", "missing", "orders_metal", "mailing"):
            with self.subTest(key=key):
                self.assertTrue(self.Home.open_block(key))
        for stage in ("draft", "sent", "purchase", "arrived", "late"):
            with self.subTest(stage=stage):
                action = self.Home.open_block("stage", stage)
                self.assertIn(("pmk_tech_spec_id", "!=", False), action["domain"])
        self.assertFalse(self.Home.open_block("stage", "nothing"))
        self.assertFalse(self.Home.open_block("nothing"))

    def test_menu(self):
        menu = self.env.ref("pmk_purchase_home.menu_purchase_home")
        root = self.env.ref("pmk_theme.menu_pmk_purchase")
        self.assertEqual(menu.parent_id, root)
        self.assertEqual(root.child_id.sorted("sequence")[0], menu, "«Главная» — первым пунктом «Закупок».")
