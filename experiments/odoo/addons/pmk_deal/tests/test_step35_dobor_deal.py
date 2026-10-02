# -*- coding: utf-8 -*-
"""Доборка ↔ сделка — разбор UX, шаг 35 (02.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. tests/__init__.py). Разметка —
собранная, как её получает браузер (get_views).

Что ловим: у доборки есть «Сделка», клиент подставляется из неё (компания
контакта), на сделке — кнопка-счётчик «Доборки» сразу за «Расчётами» (нет —
новая доборка со сделкой и клиентом, одна — она, несколько — список),
объединение сделок не оставляет доборку без сделки; калькулятор (pmk_calc)
о CRM по-прежнему не знает. Глазами (основной агент): серый ноль на кнопке,
шапка доборки «Сделка» → «Клиент | Дата» → «Изделие / объект».
"""
import ast

from lxml import etree

from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDoborDealStep35(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context, tracking_disable=True,
            mail_create_nolog=True, mail_create_nosubscribe=True))
        Partner = cls.env["res.partner"]
        cls.company = Partner.create({"name": "ООО «Кровля-ДВ» (тест 35)", "is_company": True})
        cls.person = Partner.create({"name": "Петров Иван (тест 35)", "parent_id": cls.company.id})
        cls.Lead = cls.env["crm.lead"]
        cls.deal = cls.Lead.create({
            "name": "Навес на Ленина (тест 35)", "type": "opportunity",
            "partner_id": cls.person.id})
        cls.Order = cls.env["pmk.dobor.order"]

    def _arch(self, model, view_type, xmlid=None):
        view_id = self.env.ref(xmlid).id if xmlid else False
        views = self.env[model].get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _one(self, arch, expr):
        nodes = arch.xpath(expr)
        self.assertEqual(len(nodes), 1, expr)
        return nodes[0]

    # ─── поле и подстановка клиента ──────────────────────────────────────
    def test_deal_field_without_crm_in_calculator(self):
        field = self.Order._fields["opportunity_id"]
        self.assertEqual(field.comodel_name, "crm.lead")
        self.assertEqual(field.string, "Сделка")
        self.assertTrue(field.copy, "Копия доборки остаётся в той же сделке.")
        self.assertEqual(field.ondelete, "set null")
        self.assertIn("opportunity", field.domain, "Только сделки, не лиды.")
        depends = get_manifest("pmk_calc")["depends"]
        for module in ("crm", "pmk_deal"):
            with self.subTest(module=module):
                self.assertNotIn(module, depends, "Калькулятор о CRM не знает.")

    def test_client_from_deal_only_when_empty(self):
        order = self.Order.new({"opportunity_id": self.deal.id})
        order._onchange_opportunity_id()
        self.assertEqual(order.partner_id, self.company,
                         "Клиент — компания контакта сделки, не человек.")
        other = self.env["res.partner"].create({"name": "Другой клиент (тест 35)"})
        order = self.Order.new({"opportunity_id": self.deal.id, "partner_id": other.id})
        order._onchange_opportunity_id()
        self.assertEqual(order.partner_id, other, "Выбранное руками не перетираем.")

    # ─── кнопка-счётчик «Доборки» ────────────────────────────────────────
    def test_counter_opens_new_one_or_list(self):
        self.assertEqual(self.deal.dobor_count, 0)
        action = self.deal.action_open_dobors()
        self.assertEqual(action["res_model"], "pmk.dobor.order")
        self.assertEqual(action["views"], [(False, "form")], "Нет доборок — форма новой.")
        self.assertFalse(action.get("res_id"))
        ctx = action["context"]
        self.assertEqual(ctx["default_opportunity_id"], self.deal.id)
        self.assertEqual(ctx["default_partner_id"], self.company.id)
        self.assertNotIn("default_customer", ctx, "Тема заявки — не изделие.")

        first = self.Order.with_context(**ctx).create({})
        self.assertEqual(first.opportunity_id, self.deal)
        self.assertEqual(first.partner_id, self.company)
        self.deal.invalidate_recordset(["dobor_ids", "dobor_count"])
        self.assertEqual(self.deal.dobor_count, 1)
        action = self.deal.action_open_dobors()
        self.assertEqual(action["res_id"], first.id, "Одна — она сама.")

        second = self.Order.with_context(**ctx).create({"state": "done"})
        self.deal.invalidate_recordset(["dobor_ids", "dobor_count"])
        self.assertEqual(self.deal.dobor_count, 2)
        action = self.deal.action_open_dobors()
        self.assertEqual(action["views"], [(False, "list"), (False, "form")])
        self.assertEqual(action["domain"], [("opportunity_id", "=", self.deal.id)])
        self.assertNotIn("search_default_open", action["context"],
                         "Со сделки — все доборки, и изготовленные тоже.")
        self.assertEqual(self.Order.search(action["domain"]), first | second)

    def test_counter_does_not_move_the_stage(self):
        stage = self.deal.stage_id
        self.deal.action_open_dobors()
        self.Order.create({"opportunity_id": self.deal.id})
        self.assertEqual(self.deal.stage_id, stage, "Без автоперехода.")

    def test_merge_keeps_dobor_with_a_deal(self):
        twin = self.Lead.create({
            "name": "Дубль (тест 35)", "type": "opportunity", "partner_id": self.company.id})
        on_twin = self.Order.create({"opportunity_id": twin.id})
        on_deal = self.Order.create({"opportunity_id": self.deal.id})
        merged = (self.deal | twin).merge_opportunity()
        self.assertEqual(on_twin.opportunity_id, merged,
                         "Доборка удалённой сделки не остаётся без сделки.")
        self.assertEqual(on_deal.opportunity_id, merged)
        self.assertEqual(merged.dobor_ids, on_twin | on_deal)

    # ─── виды ───────────────────────────────────────────────────────────
    def test_views_active(self):
        """Вид с упавшим xpath Odoo выключает при загрузке — ловим это."""
        for xmlid in ("pmk_deal.view_crm_lead_form_dobors",
                      "pmk_deal.view_dobor_order_form_deal",
                      "pmk_deal.view_dobor_order_list_deal",
                      "pmk_deal.view_dobor_order_search_deal"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_deal_counter_right_after_specs(self):
        arch = self._arch("crm.lead", "form")
        box = self._one(arch, "//div[@name='button_box']")
        names = [b.get("name") for b in box.iter("button")]
        self.assertEqual(names.index("action_open_dobors"), names.index("action_open_specs") + 1)
        button = self._one(arch, "//button[@name='action_open_dobors']")
        self.assertIn("oe_stat_button", button.get("class").split())
        self.assertEqual(button.get("invisible"), "type == 'lead'",
                         "Наш шаг — виден всегда, ноль серым; у лида нет, как «Расчётов».")
        stat = button.find("field")
        self.assertEqual(stat.get("name"), "dobor_count")
        self.assertEqual(stat.get("widget"), "statinfo")
        self.assertEqual(stat.get("string"), "Доборки")
        self.assertNotEqual(button.get("icon"), "fa-calculator",
                            "Надписи на кнопках скрыты темой — значок свой, не как у «Расчётов».")
        # «Расчёт и КП» в шапке — по-прежнему одна, и не задета.
        self.assertEqual(len(arch.xpath("//header/button[@name='action_open_specs']")), 1)

    def test_dobor_head_list_search(self):
        form = self._arch("pmk.dobor.order", "form", "pmk_calc.view_dobor_order_form")
        head = self._one(form, "//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]")
        blocks = [b for b in head if b.tag == "div"]
        self.assertEqual([b.get("name") for b in blocks][:2], ["pmk_f_deal", "pmk_f_partner"],
                         "Сделка — первой, перед клиентом (как у расчёта).")
        deal = blocks[0]
        self.assertIn("pmk-field--wide", deal.get("class").split())
        self.assertEqual(deal[0].tag, "label")
        field = deal[1]
        self.assertEqual(field.get("name"), "opportunity_id")
        self.assertTrue(ast.literal_eval(field.get("options") or "{}").get("no_create"))

        lst = self._arch("pmk.dobor.order", "list", "pmk_calc.view_dobor_order_list")
        cols = [f.get("name") for f in lst.xpath("/list/field")]
        self.assertEqual(cols.index("opportunity_id"), cols.index("partner_id") + 1)
        self.assertEqual(self._one(lst, "/list/field[@name='opportunity_id']").get("optional"), "hide",
                         "Сделка — в меню колонок (⚙).")

        search = self._arch("pmk.dobor.order", "search", "pmk_calc.view_dobor_order_search")
        self.assertEqual(self._one(search, "//field[@name='opportunity_id']").get("string"), "Сделка")
        self.assertEqual(self._one(search, "//filter[@name='by_deal']").get("string"), "Сделка")
