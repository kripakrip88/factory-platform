# -*- coding: utf-8 -*-
"""Таблицы одного вида, разбор UX, шаг 24: список и таблицы раскроя.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
"""
import ast

from lxml import etree

from odoo.tests import TransactionCase, tagged


def options(node):
    return ast.literal_eval(node.get("options") or "{}")


@tagged("post_install", "-at_install")
class TestCutListUnitsStep24(TransactionCase):

    def _arch(self, view_xmlid, view_type):
        views = self.env["pmk.cut.plan"].get_views([(self.env.ref(view_xmlid).id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _one(self, arch, path):
        nodes = arch.xpath(path)
        self.assertEqual(len(nodes), 1, path)
        return nodes[0]

    def test_plan_list(self):
        arch = self._arch("pmk_cut.view_cut_plan_list", "list")
        self.assertEqual(self._one(arch, "/list/field[@name='name']").get("width"), "105px",
                         "Номер РК- целиком и без 300 px пустоты.")
        for name in ("total_weight", "scrap_weight"):
            with self.subTest(field=name):
                node = self._one(arch, "/list/field[@name='%s']" % name)
                self.assertEqual(node.get("digits"), "[12,1]")
                self.assertTrue(node.get("sum"), "Итог веса остаётся.")

    def test_stock_and_parts_mm_whole(self):
        arch = self._arch("pmk_cut.view_cut_plan_form", "form")
        for rel in ("stock_ids", "part_ids"):
            with self.subTest(table=rel):
                node = self._one(arch, "//field[@name='%s']/list/field[@name='length_mm']" % rel)
                self.assertTrue(options(node).get("hide_trailing_zeros"))
