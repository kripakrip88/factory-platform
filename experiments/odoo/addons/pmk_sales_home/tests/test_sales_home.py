# -*- coding: utf-8 -*-
"""Главная продаж (16.10.2026): данные страницы, «Сделать сегодня», переходы, меню."""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.sales_home import money


@tagged("post_install", "-at_install")
class TestSalesHome(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Home = self.env["pmk.sales.home"]
        self.kp = self.env.ref("crm.stage_lead3")

    def test_money(self):
        self.assertEqual(money(24_700_000), "24,7 млн ₽")
        self.assertEqual(money(380_000), "380 тыс. ₽")
        self.assertEqual(money(0), "0 ₽")

    def test_dashboard_counts_and_todo(self):
        before = self.Home.get_dashboard()["deals"]
        today = fields.Date.context_today(self.Home)
        late = self.env["crm.lead"].create({
            "name": "Главная: просроченная", "type": "opportunity",
            "date_deadline": today - timedelta(days=2)})
        quiet = self.env["crm.lead"].create({
            "name": "Главная: КП молчит", "type": "opportunity", "stage_id": self.kp.id})
        self.env.flush_all()  # date_last_stage_update — вычисляемое: иначе перетрёт правку ниже
        self.env.cr.execute("UPDATE crm_lead SET date_last_stage_update = %s WHERE id = %s",
                            (fields.Datetime.now() - timedelta(days=5), quiet.id))
        quiet.invalidate_recordset()
        data = self.Home.get_dashboard()
        self.assertEqual(data["deals"]["open"], before["open"] + 2)
        self.assertEqual(data["deals"]["kp"], before["kp"] + 1)
        self.assertGreaterEqual(data["deals"]["kp_old"], 1)
        todo = {item["id"]: item for item in data["todo"] if item["kind"] == "deal"}
        self.assertEqual(todo[late.id]["tag"], "просрочено")
        self.assertTrue(todo[quiet.id]["tag"].startswith("КП "))
        self.assertNotIn("_open_ids", data)
        stage_names = [row["name"] for row in data["funnel"]]
        self.assertIn(self.kp.name, stage_names)
        self.assertTrue(any(row["won"] for row in data["funnel"]))

    def test_open_blocks(self):
        lead = self.env["crm.lead"].create({"name": "Главная: переход", "type": "opportunity"})
        deal = self.Home.open_block("deal", lead.id)
        self.assertEqual((deal["res_model"], deal["res_id"]), ("crm.lead", lead.id))
        kp = self.Home.open_block("kp")
        self.assertEqual(kp["res_model"], "crm.lead")
        self.assertIn(("stage_id", "=", self.kp.id), kp["domain"])
        self.assertEqual(kp["views"][0][1], "list")
        for key in ("deals", "won", "leads", "analytics", "orders", "overdue"):
            with self.subTest(key=key):
                self.assertTrue(self.Home.open_block(key))
        self.assertFalse(self.Home.open_block("nothing"))

    def test_salesman_sees_page(self):
        """Менеджер без прав администратора: страница считается, банк — по правам."""
        user = self.env["res.users"].create({
            "name": "Менеджер главной", "login": "sales_home_test",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("sales_team.group_sale_salesman_all_leads").id])]})
        data = self.Home.with_user(user).get_dashboard()
        self.assertIsNotNone(data["deals"])
        self.assertTrue(data["hello"].startswith(("Доброе", "Добрый")))

    def test_menu_first_in_sales(self):
        menu = self.env.ref("pmk_sales_home.menu_sales_home")
        self.assertEqual(menu.parent_id, self.env.ref("pmk_theme.menu_pmk_sales"))
        siblings = menu.parent_id.child_id.sorted("sequence")
        self.assertEqual(siblings[0], menu, "щелчок по «Продажам» открывает главную")
