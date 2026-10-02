# -*- coding: utf-8 -*-
"""Доборка: клиент полем, «Изделие / объект», список, справочники цветов и
красок — разбор UX, шаг 35 (02.10.2026). Доводка: человек компании в
«Клиенте» заменяется компанией, как в расчёте (шаг 11).

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py). Разметка —
собранная, как её получает браузер (get_views: все наследники применены, в
том числе «Сделка» из pmk_deal, если он стоит, — поэтому порядок блоков
проверяется относительный). «Сделка» у доборки и счётчик «Доборки» на
сделке — pmk_deal/tests/test_step35_dobor_deal.py.

Глазами (основной агент): серые строки пустых заказов в списке, ширина
колонки «Клиент», шапка «Клиент | Дата» → «Изделие / объект», обе темы.
"""
from lxml import etree

from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestDoborStep35(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.client = cls.env["res.partner"].create({
            "name": "ООО Кровля (тест 35)", "is_company": True})
        cls.Order = cls.env["pmk.dobor.order"]

    def _arch(self, model, view_type, xmlid):
        views = self.env[model].get_views([(self.env.ref(xmlid).id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _one(self, arch, expr):
        nodes = arch.xpath(expr)
        self.assertEqual(len(nodes), 1, expr)
        return nodes[0]

    # ─── поля ───────────────────────────────────────────────────────────
    def test_client_field_and_object_text(self):
        fields_ = self.Order._fields
        self.assertEqual(fields_["partner_id"].comodel_name, "res.partner")
        self.assertEqual(fields_["partner_id"].string, "Клиент")
        self.assertEqual(fields_["customer"].type, "char",
                         "Текст на месте — старые доборки не переносились.")
        self.assertEqual(fields_["customer"].string, "Изделие / объект")

    def test_person_becomes_company(self):
        """Доводка: человек компании в «Клиенте» → компания, как в расчёте
        (шаг 11). Иначе группировка «Клиент» разбивалась бы по людям."""
        Partner = self.env["res.partner"]
        person = Partner.create({"name": "Петров Иван (тест 35)", "parent_id": self.client.id})
        private = Partner.create({"name": "Сидоров Пётр (тест 35)"})
        cases = [(person, self.client, "человек компании — компания"),
                 (self.client, self.client, "компания — как есть"),
                 (private, private, "частное лицо без компании — как есть")]
        for chosen, expected, why in cases:
            with self.subTest(why=why):
                order = self.Order.new({"partner_id": chosen.id})
                order._onchange_partner_company()
                self.assertEqual(order.partner_id, expected)
        # Как в форме: правило висит на поле и срабатывает при выборе.
        with Form(self.Order) as form:
            form.partner_id = person
            self.assertEqual(form.partner_id, self.client)

    def test_form_head(self):
        arch = self._arch("pmk.dobor.order", "form", "pmk_calc.view_dobor_order_form")
        head = self._one(arch, "//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]")
        blocks = [b for b in head if b.tag == "div"]
        names = [b.get("name") for b in blocks]
        expected = [("pmk_f_partner", "partner_id"), ("pmk_f_date", "order_date"),
                    ("pmk_f_customer", "customer")]
        for name, field in expected:
            with self.subTest(block=name):
                block = blocks[names.index(name)]
                self.assertEqual(block[0].tag, "label", "Подпись первой — стиль шага 27.")
                self.assertEqual(block[1].get("name"), field)
        self.assertLess(names.index("pmk_f_partner"), names.index("pmk_f_date"))
        self.assertLess(names.index("pmk_f_date"), names.index("pmk_f_customer"))
        self.assertIn("pmk-field--wide", blocks[names.index("pmk_f_customer")].get("class").split(),
                      "Изделие / объект — во всю ширину.")
        # Шаг 27 не сломан: класс формы и окно позиции — своя форма.
        self.assertIn("pmk-doc-form", arch.get("class", "").split())
        self.assertTrue(arch.xpath("//field[@name='line_ids']/form"))

    # ─── список ─────────────────────────────────────────────────────────
    def test_list_empty_grey_client_column_area(self):
        arch = self._arch("pmk.dobor.order", "list", "pmk_calc.view_dobor_order_list")
        condition = arch.get("decoration-muted")
        self.assertEqual(condition, "total_positions == 0")
        self.assertTrue(safe_eval(condition, {"total_positions": 0}), "Пустой — серым.")
        self.assertFalse(safe_eval(condition, {"total_positions": 3}))
        self.assertTrue(arch.xpath("/list/field[@name='total_positions']"),
                        "Число «Позиций» — в строке: цвет повторён словом.")
        names = [f.get("name") for f in arch.xpath("/list/field")]
        self.assertEqual(names.index("partner_id"), names.index("order_date") + 1)
        partner = self._one(arch, "/list/field[@name='partner_id']")
        self.assertEqual(partner.get("optional"), "show")
        self.assertTrue(partner.get("width"), "Клиент не сжимается до «ООО «Ар…».")
        self.assertEqual(self._one(arch, "/list/field[@name='customer']").get("optional"), "show")
        self.assertEqual(self._one(arch, "/list/field[@name='name']").get("width"), "105px",
                         "Номер ДОБ- целиком (шаг 24).")
        self.assertEqual(self._one(arch, "/list/field[@name='total_area']").get("digits"), "[12,2]",
                         "Площадь — 2 знака.")

    def test_default_filter_not_done_and_empty_screen(self):
        action = self.env.ref("pmk_calc.action_dobor_order")
        self.assertEqual(safe_eval(action.context or "{}").get("search_default_open"), 1)
        search = self._arch("pmk.dobor.order", "search", "pmk_calc.view_dobor_order_search")
        flt = self._one(search, "//filter[@name='open']")
        self.assertEqual(flt.get("string"), "Не изготовлены")
        self.assertEqual(safe_eval(flt.get("domain")), [("state", "!=", "done")])
        self.assertIn("Не изготовлены", action.help, "Пустой экран говорит, как увидеть изготовленные.")
        self.assertIn("Новое", action.help)

    def test_search_client_and_object(self):
        search = self._arch("pmk.dobor.order", "search", "pmk_calc.view_dobor_order_search")
        self.assertEqual(self._one(search, "//field[@name='partner_id']").get("string"), "Клиент")
        self.assertEqual(self._one(search, "//field[@name='customer']").get("string"),
                         "Изделие / объект")
        self.assertEqual(self._one(search, "//filter[@name='by_partner']").get("string"), "Клиент")
        self.assertEqual(self._one(search, "//filter[@name='by_customer']").get("string"),
                         "Изделие / объект")
        self.assertFalse(search.xpath("//*[@string='Заказчик']"), "Одно понятие — одно слово.")

    # ─── печатный лист ──────────────────────────────────────────────────
    def test_sheet_customer_line(self):
        cases = [
            ({"partner_id": self.client.id, "customer": " навес на Ленина 5 "},
             "ООО Кровля (тест 35) · навес на Ленина 5"),
            ({"customer": "Проверка расчёта"}, "Проверка расчёта"),
            ({"partner_id": self.client.id}, "ООО Кровля (тест 35)"),
            ({}, "—"),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(self.Order.create(values)._sheet_customer(), expected)
        order = self.Order.create({"partner_id": self.client.id, "customer": "навес"})
        self.assertIn("Заказчик: <b>ООО Кровля (тест 35) · навес</b>", order._sheet_html(),
                      "Лист — в прежней ячейке «Заказчик».")

    # ─── справочники ────────────────────────────────────────────────────
    def test_reference_menus_and_screens(self):
        cases = [
            ("pmk_calc.menu_pmk_calc_paint", "pmk_calc.action_paint_coating",
             "pmk_calc.view_paint_coating_list", "Краски (ЛКП)"),
            ("pmk_calc.menu_pmk_calc_coating", "pmk_calc.action_dobor_coating",
             "pmk_calc.view_dobor_coating_list", "Цвета доборки (RAL)"),
        ]
        for menu_xmlid, action_xmlid, view_xmlid, title in cases:
            with self.subTest(title=title):
                menu = self.env.ref(menu_xmlid)
                action = self.env.ref(action_xmlid)
                self.assertEqual(menu.name, title)
                self.assertEqual(menu.action, action)
                self.assertEqual(action.name, title, "Заголовок экрана — как пункт меню.")
                arch = self._arch(action.res_model, "list", view_xmlid)
                self.assertEqual(arch.get("string"), title)
        names = self.env.ref("pmk_calc.menu_pmk_calc_reference").child_id.mapped("name")
        for old in ("Лакокрасочные покрытия", "Покрытия доборки", "Покрытия"):
            with self.subTest(old=old):
                self.assertNotIn(old, names)
