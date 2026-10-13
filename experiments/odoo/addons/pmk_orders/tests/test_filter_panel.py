# -*- coding: utf-8 -*-
"""Панель «Фильтр» над списками, как в МоёмСкладе (13.10.2026): подключена и знает свои поля."""
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
        # Планировщик узнаётся по ключу контекста окна — он у окна есть.
        ctx = self.env.ref("pmk_orders.action_orders").context
        self.assertIn("default_pmk_metal", ctx)
