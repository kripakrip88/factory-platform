# -*- coding: utf-8 -*-
"""Таблицы одного вида, разбор UX, шаг 24: единицы и итоги в списках pmk_calc.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk24_test -i pmk_deal,pmk_cut,pmk_laser --test-enable \\
         --test-tags /pmk_calc,/pmk_bridge,/pmk_cut,/pmk_laser,/pmk_deal,/pmk_theme \\
         --stop-after-init --http-port 8099

Разметка — собранная, как её получает браузер (get_views: все наследники
применены). Глазами это не заменяет: высоту строки, перенос шапки и ширину
номера смотрит основной агент в браузере. Здесь ловится то, что ломается
молча: вернувшийся итог «кг/м», сумма толщин в строке группы, граммы в весе.
"""
import ast

from lxml import etree

from odoo.tests import TransactionCase, tagged


def options(node):
    return ast.literal_eval(node.get("options") or "{}")


@tagged("post_install", "-at_install")
class TestListUnitsStep24(TransactionCase):

    def _arch(self, model, view_type, view_xmlid=None):
        view_id = self.env.ref(view_xmlid).id if view_xmlid else False
        views = self.env[model].get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _one(self, arch, path):
        nodes = arch.xpath(path)
        self.assertEqual(len(nodes), 1, path)
        return nodes[0]

    def test_reference_numbers_not_summed_in_groups(self):
        """Строка группы справочника пустая: сумма толщин и масс — бессмыслица.

        Что складывать в строке группы, браузер решает по aggregator из
        fields_get (web/model/relational_model/utils.js,
        getAggregateSpecifications) — его и проверяем."""
        cases = {
            "pmk.metal.profile": ["mass_per_meter", "surface_per_meter", "du", "outer_mm", "wall_mm"],
            "pmk.metal.sheet": ["thickness_mm", "mass_per_sqm"],
            "pmk.metal.fastener": ["weight_kg"],
            "pmk.paint.coating": ["consumption", "base_thickness_um", "layers"],
        }
        for model, names in cases.items():
            info = self.env[model].fields_get(names, ["aggregator"])
            for name in names:
                with self.subTest(model=model, field=name):
                    self.assertFalse(info[name].get("aggregator"))
                    self.assertIsNone(self.env[model]._fields[name].aggregator)

    def test_reference_lists_without_totals(self):
        profile = self._arch("pmk.metal.profile", "list", "pmk_calc.view_metal_profile_list")
        sheet = self._arch("pmk.metal.sheet", "list", "pmk_calc.view_metal_sheet_list")
        self.assertIsNone(self._one(profile, "//field[@name='mass_per_meter']").get("sum"),
                          "Итог «кг/м» снят — сумма масс метра ничего не значит.")
        self.assertIsNone(self._one(sheet, "//field[@name='mass_per_sqm']").get("sum"))
        thickness = self._one(sheet, "//field[@name='thickness_mm']")
        self.assertTrue(options(thickness).get("hide_trailing_zeros"),
                        "Толщина листа — «4», а не «4,00».")

    def test_spec_list_weight_in_tons(self):
        """Список расчётов: тонны до килограмма видны, килограммы — в ⚙."""
        arch = self._arch("pmk.metal.spec", "list", "pmk_calc.view_metal_spec_list")
        tons = self._one(arch, "//field[@name='total_weight_t']")
        self.assertIsNone(tons.get("optional"), "Колонка тонн видна всегда.")
        self.assertIsNone(tons.get("column_invisible"))
        self.assertEqual(tons.get("digits"), "[12,3]")
        self.assertEqual(tons.get("string"), "Вес, т")
        self.assertTrue(tons.get("sum"))
        kilos = self._one(arch, "//field[@name='total_weight']")
        self.assertEqual(kilos.get("optional"), "hide", "Скрыта обратимо — в меню колонок.")
        self.assertEqual(kilos.get("digits"), "[12,0]", "Без граммов.")
        name = self._one(arch, "//field[@name='name']")
        self.assertEqual(name.get("width"), "105px", "Номер СМ- не обрезается (шаг 2).")

    def test_spec_product_dialog_mm_whole(self):
        """Окно изделия: миллиметры без «,0», дробные остаются дробными."""
        arch = self._arch("pmk.metal.spec", "form")
        dialog = "//field[@name='product_ids']/form"
        for path in (
            dialog + "//field[@name='line_linear_ids']/list/field[@name='length_mm']",
            dialog + "//field[@name='line_sheet_ids']/list/field[@name='a_mm']",
            dialog + "//field[@name='line_sheet_ids']/list/field[@name='b_mm']",
        ):
            with self.subTest(path=path):
                self.assertTrue(options(self._one(arch, path)).get("hide_trailing_zeros"))

    def test_spec_form_weights_one_digit(self):
        """Вес в таблицах расчёта — с одним знаком, как карточка над ними.

        Итог колонки берёт знаки колонки (pmk_theme, list_table_rules.js):
        без digits в виде он получил бы знаки поля (12,3) — граммы в строке
        «Итого, кг», тогда как карточка показывает один знак. Исключение —
        вес ШТУКИ метиза: 0,010–0,099 кг с одним знаком стали бы «0,0»."""
        arch = self._arch("pmk.metal.spec", "form")
        self.assertEqual(
            self._one(arch, "//div[contains(@class, 'pmk-kpi__sub')]/field[@name='total_weight']")
            .get("digits"), "[12,1]", "Карточка веса — один знак.")
        products = "//field[@name='product_ids']"
        dialog = products + "/form"
        one_digit = [
            products + "/list/field[@name='weight_one']",
            products + "/list/field[@name='weight_total']",
            dialog + "/group//field[@name='weight_one']",
            dialog + "/group//field[@name='weight_total']",
        ]
        for tab in ("line_linear_ids", "line_sheet_ids", "line_paint_ids"):
            one_digit += [
                dialog + "//field[@name='%s']/list/field[@name='weight_one']" % tab,
                dialog + "//field[@name='%s']/list/field[@name='weight_total']" % tab,
            ]
        one_digit.append(dialog + "//field[@name='line_fastener_ids']/list/field[@name='weight_total']")
        for path in one_digit:
            with self.subTest(path=path):
                self.assertEqual(self._one(arch, path).get("digits"), "[12,1]")
        piece = self._one(
            arch, dialog + "//field[@name='line_fastener_ids']/list/field[@name='weight_one']")
        self.assertEqual(piece.get("digits"), "[12,3]", "Вес штуки метиза — с граммами.")
        for path in (
            products + "/list/field[@name='weight_total']",
            dialog + "//field[@name='line_linear_ids']/list/field[@name='weight_total']",
            dialog + "//field[@name='line_sheet_ids']/list/field[@name='weight_total']",
            dialog + "//field[@name='line_fastener_ids']/list/field[@name='weight_total']",
            dialog + "//field[@name='line_paint_ids']/list/field[@name='weight_total']",
        ):
            with self.subTest(total=path):
                self.assertTrue(self._one(arch, path).get("sum"), "Итог «Итого, кг» остаётся.")

    def test_dobor_form_weights_one_digit(self):
        """Доборка: вес в строках, итог таблицы и карточка «Общий вес, кг» —
        с одним знаком (документ разбора: «вес с одним знаком»)."""
        arch = self._arch("pmk.dobor.order", "form")
        self.assertEqual(self._one(arch, "//form/sheet//field[@name='total_weight']").get("digits"),
                         "[12,1]", "Карточка «Общий вес, кг» — как итог таблицы под ней.")
        total = self._one(arch, "//field[@name='line_ids']/list/field[@name='weight_total']")
        self.assertEqual(total.get("digits"), "[12,1]")
        self.assertTrue(total.get("sum"))
        for name in ("weight_one", "weight_total"):
            with self.subTest(field=name):
                node = self._one(arch, "//field[@name='line_ids']/form//field[@name='%s']" % name)
                self.assertEqual(node.get("digits"), "[12,1]")

    def test_dobor_list(self):
        arch = self._arch("pmk.dobor.order", "list", "pmk_calc.view_dobor_order_list")
        self.assertEqual(self._one(arch, "//field[@name='name']").get("width"), "105px",
                         "Номер ДОБ- целиком и без половины таблицы.")
        self.assertEqual(self._one(arch, "//field[@name='total_area']").get("digits"), "[12,2]")
        weight = self._one(arch, "//field[@name='total_weight']")
        self.assertEqual(weight.get("digits"), "[12,1]", "Вес без граммов.")
        self.assertTrue(weight.get("sum"), "Итог веса заказа остаётся.")
        # У плашки badge ядро не знает предела ширины: без width свободное
        # место делилось бы между статусом и клиентом.
        state = self._one(arch, "//field[@name='state']")
        self.assertEqual(state.get("widget"), "badge")
        self.assertEqual(state.get("width"), "110px", "Статус не растягивается на полтаблицы.")

    def test_dobor_lines_mm_whole(self):
        arch = self._arch("pmk.dobor.order", "form")
        for name in ("plank_length", "developed_width", "strip_waste"):
            with self.subTest(field=name):
                node = self._one(arch, "//field[@name='line_ids']/list/field[@name='%s']" % name)
                self.assertTrue(options(node).get("hide_trailing_zeros"))
