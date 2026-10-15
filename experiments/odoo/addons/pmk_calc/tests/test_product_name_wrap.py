# -*- coding: utf-8 -*-
"""Название изделия в списке расчёта переносится, колонка не уже 200 px
(Антон 15.10.2026: «название изделия не влазит в строку»)."""
from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path


@tagged("post_install", "-at_install")
class TestProductNameWrap(TransactionCase):

    def test_name_column_widget(self):
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_view(view_type="form")["arch"])
        name = arch.xpath("//field[@name='product_ids']/list/field[@name='name']")
        self.assertEqual(name[0].get("widget"), "pmk_product_name")

    def test_short_headers(self):
        """Подписи без единиц, цены без «руб» (Антон 15.10.2026)."""
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_view(view_type="form")["arch"])
        cols = {f.get("name"): f for f in arch.xpath("//field[@name='product_ids']/list/field")}
        self.assertEqual(cols["qty"].get("string"), "Количество")
        self.assertEqual(cols["weight_one"].get("string"), "Вес")
        self.assertEqual(cols["weight_total"].get("string"), "Вес всего")
        if "price_customer_unit" in cols:  # мост стоит
            for name in ("price_customer_unit", "price_customer_total"):
                self.assertIn("no_symbol", cols[name].get("options") or "")

    def test_assets(self):
        with open(file_path("pmk_calc/static/src/js/product_lines_field.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('add("pmk_product_name"', js)
        self.assertIn("listViewWidth: [200]", js)
        with open(file_path("pmk_calc/static/src/scss/dobor_builder.scss"), encoding="utf-8") as fh:
            scss = fh.read()
        self.assertIn('.o_field_pmk_product_lines .o_list_table > tbody > tr.o_data_row > td.o_data_cell[name="name"]',
                      scss)
