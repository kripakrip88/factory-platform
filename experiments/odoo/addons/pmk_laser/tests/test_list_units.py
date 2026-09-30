# -*- coding: utf-8 -*-
"""Таблицы одного вида, разбор UX, шаг 24: списки лазерного участка.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
Тесты чертежей (test_drawing.py) — обычный unittest без базы, их Odoo не
запускает; этот файл — наоборот, только внутри Odoo.

Проверяем то, что ломается молча: сумма киловатт и толщин в строке группы,
обрезанный номер ЛР-, копейки премии в списке.
"""
import ast

from lxml import etree

from odoo.tests import TransactionCase, tagged


def options(node):
    return ast.literal_eval(node.get("options") or "{}")


@tagged("post_install", "-at_install")
class TestLaserListUnitsStep24(TransactionCase):

    def _arch(self, model, view_xmlid, view_type="list"):
        views = self.env[model].get_views([(self.env.ref(view_xmlid).id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _field(self, arch, name, path="/list/field"):
        nodes = arch.xpath("%s[@name='%s']" % (path, name))
        self.assertEqual(len(nodes), 1, name)
        return nodes[0]

    def test_not_summed_in_groups(self):
        cases = {
            "pmk.laser.machine": ["power_kw", "load_min", "unload_min", "max_thickness_mm",
                                  "max_width_mm", "max_length_mm"],
            "pmk.laser.job": ["kerf_mm", "min_offcut_mm", "premium_rate_rub",
                              "contour_gap_pct", "utilization_pct",
                              # Связанные с листом: aggregator=None приходит из
                              # справочника pmk_calc, своего атрибута у поля нет.
                              "thickness_mm", "mass_per_sqm"],
        }
        for model, names in cases.items():
            for name in names:
                with self.subTest(model=model, field=name):
                    self.assertIsNone(self.env[model]._fields[name].aggregator)

    def test_meaningful_sums_kept(self):
        """Ёмкость смены, листы, вес, минуты и премия складываются, как раньше:
        на них стоит сводная «Загрузки участка» и итоги списков."""
        self.assertEqual(self.env["pmk.laser.machine"]._fields["shift_minutes"].aggregator, "sum")
        job = self.env["pmk.laser.job"]._fields
        for name in ("sheet_count", "useful_mass_kg", "premium_rub",
                     "planned_minutes", "actual_minutes", "plan_missing"):
            with self.subTest(field=name):
                self.assertEqual(job[name].aggregator, "sum")

    def test_job_list(self):
        arch = self._arch("pmk.laser.job", "pmk_laser.view_laser_job_list")
        self.assertEqual(self._field(arch, "name").get("width"), "105px")
        premium = self._field(arch, "premium_rub")
        self.assertEqual(premium.get("digits"), "[10,0]", "Премия в списке — без копеек.")
        self.assertTrue(premium.get("sum"))

    def test_load_list(self):
        arch = self._arch("pmk.laser.job", "pmk_laser.view_laser_load_list")
        self.assertEqual(self._field(arch, "name").get("width"), "105px")

    def test_measure_and_offcut_lists(self):
        for model, xmlid in (("pmk.laser.measure", "pmk_laser.view_laser_measure_list"),
                             ("pmk.laser.offcut", "pmk_laser.view_laser_offcut_list")):
            arch = self._arch(model, xmlid)
            with self.subTest(view=xmlid):
                self.assertEqual(self._field(arch, "job_id").get("width"), "105px")
                self.assertTrue(options(self._field(arch, "thickness_mm")).get("hide_trailing_zeros"))
        offcut = self._arch("pmk.laser.offcut", "pmk_laser.view_laser_offcut_list")
        self.assertEqual(self._field(offcut, "area_m2").get("digits"), "[10,2]")

    def test_norm_and_machine_lists(self):
        norm = self._arch("pmk.laser.norm", "pmk_laser.view_laser_norm_list")
        self.assertTrue(options(self._field(norm, "thickness_mm")).get("hide_trailing_zeros"))
        machine = self._arch("pmk.laser.machine", "pmk_laser.view_laser_machine_list")
        self.assertTrue(options(self._field(machine, "max_thickness_mm")).get("hide_trailing_zeros"))

    def test_job_parts_mm_whole(self):
        arch = self._arch("pmk.laser.job", "pmk_laser.view_laser_job_form", "form")
        node = self._field(arch, "cut_length_mm", "//field[@name='part_ids']/list/field")
        self.assertTrue(options(node).get("hide_trailing_zeros"))
