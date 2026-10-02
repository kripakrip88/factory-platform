# -*- coding: utf-8 -*-
"""Раскрой: убрать совсем — разбор UX, шаг 29.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
Разметка — собранная, как её получает браузер (get_views).

Что ловим: вид шага жив; «Теоретический минимум» ушёл в меню колонок (⚙)
и скрыт в окне строки результата; «Очерёдность» заготовок — на виду (по ней
обрезки идут в дело первыми). «Название» заготовки шаг 29 тоже прятал — его
вернул шаг 35 (пометка «(из прайса)» у хлыста-докупки), см.
test_stock_name_back_since_step35.
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged

HIDDEN = ("1", "True", "true")


@tagged("post_install", "-at_install")
class TestCutHideStep29(TransactionCase):

    def _form(self):
        view = self.env.ref("pmk_cut.view_cut_plan_form")
        views = self.env["pmk.cut.plan"].get_views([(view.id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def _one(self, arch, expr):
        nodes = arch.xpath(expr)
        self.assertEqual(len(nodes), 1, expr)
        return nodes[0]

    def test_view_active(self):
        self.assertTrue(self.env.ref("pmk_cut.view_cut_plan_form_step29").active)

    def test_stock_name_back_since_step35(self):
        """Шаг 35 вернул «Название»: в нём «(из прайса)» у хлыста-докупки."""
        arch = self._form()
        name = self._one(arch, "//field[@name='stock_ids']/list/field[@name='name']")
        self.assertEqual(name.get("optional"), "show", "На виду, убрать — галочкой в ⚙.")
        step29 = self.env.ref("pmk_cut.view_cut_plan_form_step29").arch
        self.assertNotIn("@name='name'", step29, "Xpath шага 29 на «Название» снят.")
        priority = self._one(arch, "//field[@name='stock_ids']/list/field[@name='priority']")
        self.assertNotIn(priority.get("optional"), ("hide",))
        self.assertNotIn(priority.get("column_invisible"), HIDDEN)

    def test_lower_bound_hidden(self):
        arch = self._form()
        column = self._one(arch, "//field[@name='result_ids']/list/field[@name='lower_bound']")
        self.assertEqual(column.get("optional"), "hide")
        in_form = self._one(arch, "//field[@name='result_ids']/form//field[@name='lower_bound']")
        self.assertIn(in_form.get("invisible"), HIDDEN)
        # «Взято хлыстов» рядом — на виду.
        bars = self._one(arch, "//field[@name='result_ids']/list/field[@name='bars_used']")
        self.assertNotEqual(bars.get("optional"), "hide")
