# -*- coding: utf-8 -*-
"""Колонки заданий и станков лазера — разбор UX, шаг 25.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
"""
import ast

from lxml import etree

from odoo.tests import TransactionCase, tagged

from ..models.machine import table_size_label

HIDDEN = ("1", "True", "true")


@tagged("post_install", "-at_install")
class TestLaserListColumnsStep25(TransactionCase):

    def _arch(self, model, view_xmlid):
        views = self.env[model].get_views([(self.env.ref(view_xmlid).id, "list")])
        return etree.fromstring(views["views"]["list"]["arch"])

    def _one(self, arch, name):
        nodes = arch.xpath("/list/field[@name='%s']" % name)
        self.assertEqual(len(nodes), 1, name)
        return nodes[0]

    def test_job_list(self):
        arch = self._arch("pmk.laser.job", "pmk_laser.view_laser_job_list")
        for name in ("partner_id", "sheet_id", "planned_minutes", "actual_minutes"):
            with self.subTest(hidden=name):
                self.assertEqual(self._one(arch, name).get("optional"), "hide",
                                 "В меню колонок, не убрана.")
        thickness = self._one(arch, "thickness_mm")
        self.assertIsNone(thickness.get("optional"), "Толщина видна всегда — вместо листа.")
        self.assertTrue(ast.literal_eval(thickness.get("options") or "{}").get("hide_trailing_zeros"))
        scrap = self._one(arch, "scrap_mass_kg")
        self.assertTrue(scrap.get("sum"), "Лом — с итогом внизу.")
        self.assertEqual(scrap.get("optional"), "show")
        drawings = self._one(arch, "parts_without_drawing")
        self.assertEqual(drawings.get("decoration-danger"), "parts_without_drawing > 0")
        self.assertEqual(drawings.get("optional"), "show")
        names = [f.get("name") for f in arch.xpath("/list/field")]
        self.assertEqual(names.index("thickness_mm"), names.index("sheet_id") + 1)
        self.assertEqual(names.index("scrap_mass_kg"), names.index("useful_mass_kg") + 1)
        # Шаг 24 не сломан.
        self.assertEqual(self._one(arch, "name").get("width"), "105px")
        self.assertEqual(self._one(arch, "premium_rub").get("digits"), "[10,0]")

    def test_machine_list(self):
        arch = self._arch("pmk.laser.machine", "pmk_laser.view_laser_machine_list")
        names = [f.get("name") for f in arch.xpath("/list/field")]
        self.assertEqual(names.index("table_size_label"), names.index("max_thickness_mm") + 1)
        self.assertIn(self._one(arch, "workcenter_id").get("column_invisible"), HIDDEN,
                      "Рабочий центр убран и из меню колонок; узел на месте.")

    def test_table_size_label(self):
        machine = self.env["pmk.laser.machine"].create({
            "name": "Лазер (тест 25)", "max_width_mm": 1500, "max_length_mm": 6000})
        self.assertEqual(machine.table_size_label, "1500×6000")
        machine.max_width_mm = 2000
        self.assertEqual(machine.table_size_label, "2000×6000")
        machine.max_length_mm = 0
        self.assertFalse(machine.table_size_label, "Не задан размер — пусто, а не «2000×0».")

    def test_table_size_label_plain(self):
        self.assertEqual(table_size_label(1500.0, 6000.0), "1500×6000")
        self.assertEqual(table_size_label(1500.5, 3000.0), "1500.5×3000")
        self.assertFalse(table_size_label(0.0, 6000.0))
        self.assertFalse(table_size_label(1500.0, None))
