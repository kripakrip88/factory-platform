# -*- coding: utf-8 -*-
"""Колонки списка раскроя — разбор UX, шаг 25.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCutListColumnsStep25(TransactionCase):

    def _arch(self):
        view_id = self.env.ref("pmk_cut.view_cut_plan_list").id
        views = self.env["pmk.cut.plan"].get_views([(view_id, "list")])
        return etree.fromstring(views["views"]["list"]["arch"])

    def test_plan_list(self):
        arch = self._arch()
        fields_ = arch.xpath("/list/field")
        names = [f.get("name") for f in fields_]
        self.assertEqual(names[:5], ["name", "date", "partner_id", "spec_id", "note"])
        spec = fields_[names.index("spec_id")]
        self.assertEqual(spec.get("string"), "Расчёт")
        self.assertEqual(spec.get("width"), "105px", "Номер СМ- не обрезается.")
        self.assertEqual(fields_[names.index("total_bars")].get("optional"), "hide")
        # У списка есть меню колонок: всё, кроме номера и даты, — optional.
        for node in fields_[2:]:
            with self.subTest(field=node.get("name")):
                self.assertIn(node.get("optional"), ("show", "hide"))
        # Шаг 24 не сломан: итоги веса на месте.
        for name in ("total_weight", "scrap_weight"):
            with self.subTest(total=name):
                self.assertTrue(fields_[names.index(name)].get("sum"))
