# -*- coding: utf-8 -*-
"""Форма раскроя — один стиль подписей и бледные нули (разбор UX, шаг 27).

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).

Рамки «Ширины пропила» и «Годного остатка от» и серые «0,00» смотрит
основной агент глазами. Здесь — класс формы, на который опираются стили
темы, и согласие вложенных таблиц на бледные нули (pmk_theme,
js/list_zero.js: во вложенных таблицах нули глушатся только по нему).
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCutFormStep27(TransactionCase):

    def _form(self):
        view = self.env.ref("pmk_cut.view_cut_plan_form")
        views = self.env["pmk.cut.plan"].get_views([(view.id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_form_class(self):
        self.assertIn("pmk-doc-form", self._form().get("class", "").split())

    def test_nested_zero_opt_in(self):
        arch = self._form()
        for rel in ("stock_ids", "part_ids", "result_ids"):
            with self.subTest(table=rel):
                lists = arch.xpath("//field[@name='%s']/list" % rel)
                self.assertEqual(len(lists), 1)
                self.assertIn("o_pmk_zero_muted", (lists[0].get("class") or "").split())

    def test_head_fields_are_inputs(self):
        """«Ширина пропила» и «Годный остаток от» — поля ввода в шапке, не
        только для чтения: рамку им возвращает тема по классу формы."""
        arch = self._form()
        for name in ("kerf_mm", "min_useful_mm"):
            with self.subTest(field=name):
                node = arch.xpath("//div[contains(@class, 'pmk-field')]/field[@name='%s']" % name)
                self.assertEqual(len(node), 1)
                self.assertNotIn(node[0].get("readonly"), ("1", "True"))
                self.assertEqual(self.env["pmk.cut.plan"]._fields[name].type, "float")
