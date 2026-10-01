# -*- coding: utf-8 -*-
"""Лазерная резка: убрать совсем и спрятать до востребования — разбор UX,
шаг 29.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
Разметка — собранная, как её получает браузер (get_views).

Что ловим: виды шага живы; «Раскладка» листов — в меню колонок (⚙);
«Заказ» задания и «Рабочий центр» станка видны только заполненными (данные
не прячутся); кнопки «Начал» / «Закончил» в строке листа на месте.
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLaserHideStep29(TransactionCase):

    def _form(self, model, xmlid):
        views = self.env[model].get_views([(self.env.ref(xmlid).id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def _one(self, arch, expr):
        nodes = arch.xpath(expr)
        self.assertEqual(len(nodes), 1, expr)
        return nodes[0]

    def test_views_active(self):
        for xmlid in ("pmk_laser.view_laser_job_form_step29", "pmk_laser.view_laser_machine_form_step29"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_job_form(self):
        arch = self._form("pmk.laser.job", "pmk_laser.view_laser_job_form")
        nest = self._one(arch, "//field[@name='sheet_ids']/list/field[@name='nest_index']")
        self.assertEqual(nest.get("optional"), "hide")
        order = self._one(arch, "//sheet//field[@name='sale_order_id']")
        self.assertEqual(order.get("invisible"), "not sale_order_id")
        # Кнопки оператора в строке листа — на месте.
        for name in ("action_start_cut", "action_finish_cut"):
            with self.subTest(button=name):
                self._one(arch, "//field[@name='sheet_ids']/list/button[@name='%s']" % name)
        # Расчёт рядом с заказом — на виду: режут по нему.
        specs = [node for node in arch.xpath("//sheet//group/field[@name='spec_id']")
                 if not node.get("invisible")]
        self.assertTrue(specs)

    def test_machine_form(self):
        arch = self._form("pmk.laser.machine", "pmk_laser.view_laser_machine_form")
        workcenter = self._one(arch, "//field[@name='workcenter_id']")
        self.assertEqual(workcenter.get("invisible"), "not workcenter_id")
