# -*- coding: utf-8 -*-
"""Фильтр документов в окне ползунков, как в МоёмСкладе (13.10.2026): подключён и знает свои поля."""
from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open


@tagged("post_install", "-at_install")
class TestFilterPanel(TransactionCase):

    def test_assets_and_fields(self):
        assets = get_manifest("pmk_orders")["assets"]["web.assets_backend"]
        for name in ("js/filter_panel.js", "xml/filter_panel.xml", "scss/filter_panel.scss"):
            self.assertIn("pmk_orders/static/src/" + name, assets)
        with file_open("pmk_orders/static/src/js/filter_panel.js") as f:
            js = f.read()
        # Поля панели есть у моделей (иначе панель их молча пропустит — проверяем, что не все).
        for model, names in (("sale.order", ["date_order", "partner_id", "pmk_org_id", "amount_total"]),
                             ("pmk.metal.spec", ["date", "partner_id", "opportunity_id"]),
                             ("crm.lead", ["create_date", "stage_id", "user_id", "expected_revenue"]),
                             ("project.task", ["pmk_date_due", "stage_id", "user_ids", "pmk_amount",
                                               "pmk_sale_order_id", "pmk_overdue"])):
            for name in names:
                with self.subTest(model=model, field=name):
                    self.assertIn(name, self.env[model]._fields)
                    self.assertIn('"%s"' % name, js)
        # Место — окно ползунков (SearchBarMenu), а не над списком.
        with file_open("pmk_orders/static/src/xml/filter_panel.xml") as f:
            xml = f.read()
        self.assertIn('t-inherit="web.SearchBarMenu"', xml)
        self.assertNotIn("web.ListView", xml)
        # «Мои …» (упрощение 25.10.2026): поле пользователя есть у каждой модели.
        for model, name in (("sale.order", "user_id"), ("pmk.metal.spec", "create_uid"),
                            ("crm.lead", "user_id"), ("project.task", "user_ids")):
            with self.subTest(model=model, mine=name):
                self.assertIn(name, self.env[model]._fields)
                self.assertRegex(js, r'name: "%s", type: "mine"' % name)
        # Статусы МоегоСклада — ключи как в МС (подписи короче, ключи нет).
        for state in ("Предоплата получена", "В производство", "Заказ готов", "Заказ отгружен", "Не актуальна"):
            self.assertIn('["%s", ' % state, js)
        # Штатное меню — свёрнуто под ссылку, кнопка одна — «Показать N».
        self.assertIn("pmk-filter--std", xml)
        self.assertIn("countLabel", xml)
        self.assertNotIn("Найти", xml)
        with file_open("pmk_orders/static/src/scss/filter_panel.scss") as f:
            scss = f.read()
        self.assertIn(":has(> .pmk-filter:not(.pmk-filter--std)) > :not(.pmk-filter)", scss)
        # Планировщик узнаётся по ключу контекста окна — он у окна есть.
        ctx = self.env.ref("pmk_orders.action_orders").context
        self.assertIn("default_pmk_metal", ctx)
