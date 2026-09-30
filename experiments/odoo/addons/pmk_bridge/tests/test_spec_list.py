# -*- coding: utf-8 -*-
"""Список расчётов в сборе (pmk_calc + мост + сделка), разбор UX, шаг 24.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).

До шага 24 мост прятал колонку тонн (`optional="hide"`): она повторяла
килограммы, а номер обрезался. Теперь видны тонны до килограмма, килограммы —
в меню колонок. Ловим, чтобы xpath моста не вернул скрытие и чтобы ни один из
трёх видов списка не выключился молча (упавший xpath Odoo выключает).
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpecListStep24(TransactionCase):

    def _list(self):
        view_id = self.env.ref("pmk_calc.view_metal_spec_list").id
        views = self.env["pmk.metal.spec"].get_views([(view_id, "list")])
        return etree.fromstring(views["views"]["list"]["arch"])

    def test_views_active(self):
        xmlids = ["pmk_calc.view_metal_spec_list", "pmk_bridge.view_metal_spec_list_cost"]
        if self.env["ir.module.module"]._get("pmk_deal").state == "installed":
            xmlids.append("pmk_deal.view_metal_spec_list_deal")
        for xmlid in xmlids:
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_weight_columns(self):
        arch = self._list()
        tons = arch.xpath("//field[@name='total_weight_t']")
        self.assertEqual(len(tons), 1)
        tons = tons[0]
        self.assertIsNone(tons.get("optional"), "Мост больше не прячет тонны.")
        self.assertEqual(tons.get("digits"), "[12,3]")
        self.assertEqual(tons.get("string"), "Вес, т")
        self.assertTrue(tons.get("sum"))
        kilos = arch.xpath("//field[@name='total_weight']")[0]
        self.assertEqual(kilos.get("optional"), "hide")
        self.assertEqual(arch.xpath("//field[@name='name']")[0].get("width"), "105px")

    def test_money_after_tons(self):
        """Деньги моста встают сразу за тоннами — xpath «after» нашёл узел."""
        names = [f.get("name") for f in self._list().iter("field")]
        at = names.index("total_weight_t")
        self.assertEqual(names[at + 1], "total_cost_fact")
        self.assertIn("price_customer_total", names[at:])
        self.assertIn("margin_pct", names[at:])
