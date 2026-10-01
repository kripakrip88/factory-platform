# -*- coding: utf-8 -*-
"""Список «Продажи → Клиенты» — свой вид, разбор UX, шаг 25.

Раньше «Клиенты» и «Закупки → Поставщики» открывали один штатный вид, и выбор
колонок в ⚙ у них был общим (браузер помнит его по модели и виду). Ловим:
меню открывает наш вид, в нём нужные колонки и нет лишних, штатный вид не
тронут. Глазами (ширина, перенос шапки) — в браузере.
"""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCustomerListStep25(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.view = cls.env.ref("pmk_partner.view_partner_customer_list")
        cls.admin = cls.env.ref("base.user_admin")
        # «Сделок» видит тот, кто видит сделки (группа поля у crm).
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("sales_team.group_sale_salesman").id)]})

    def _arch(self, view_id):
        views = self.env["res.partner"].with_user(self.admin).get_views([(view_id, "list")])
        return etree.fromstring(views["views"]["list"]["arch"])

    def test_menu_opens_our_view(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("account.res_partner_action_customer")
        self.assertEqual(tuple(action["views"][0]), (self.view.id, "list"),
                         "Список «Клиентов» — наш, первым.")
        modes = [mode for _view, mode in action["views"]]
        self.assertIn("form", modes, "Карточка клиента открывается как раньше.")

    def test_columns(self):
        arch = self._arch(self.view.id)
        self.assertIsNone(arch.get("sample"), "Пустой экран без выдуманных клиентов.")
        visible = [f.get("name") for f in arch.xpath("/list/field")
                   if f.get("column_invisible") not in ("1", "True")]
        self.assertEqual(visible, ["display_name", "vat", "city", "phone", "email",
                                   "user_id", "pmk_deal_count"])
        labels = {f.get("name"): f.get("string") for f in arch.xpath("/list/field")}
        self.assertEqual(labels["vat"], "ИНН")
        self.assertEqual(labels["email"], "Эл. почта")
        self.assertEqual(labels["user_id"], "Менеджер")
        self.assertIsNone(labels["pmk_deal_count"], "Подпись — из поля.")
        self.assertEqual(self.env["res.partner"].fields_get(["pmk_deal_count"])
                         ["pmk_deal_count"]["string"], "Сделок")
        self.assertFalse(arch.xpath("//field[@name='opportunity_count']"),
                         "Штатный счётчик считал лиды и проигранные.")
        for name in ("avatar_128", "country_id", "application_statistics",
                     "activity_ids", "properties", "category_id"):
            with self.subTest(gone=name):
                self.assertFalse(arch.xpath("//field[@name='%s']" % name))
        vat = arch.xpath("/list/field[@name='vat']")[0]
        self.assertEqual(vat.get("readonly"), "1", "ИНН в списке не правится (multi_edit).")
        # У всех колонок, кроме названия, есть optional — значит, есть ⚙.
        for node in arch.xpath("/list/field")[2:]:
            with self.subTest(optional=node.get("name")):
                self.assertEqual(node.get("optional"), "show")

    def test_deal_count(self):
        """Только сделки, кроме проигранных; лид сделкой не считается."""
        company = self.env["res.partner"].create({"name": "ООО «Клиент 25»", "is_company": True})
        person = self.env["res.partner"].create({"name": "Иван (тест 25)", "parent_id": company.id})
        Lead = self.env["crm.lead"]
        Lead.create({"name": "Сделка 25", "type": "opportunity", "partner_id": person.id})
        Lead.create({"name": "Выиграна 25", "type": "opportunity", "partner_id": company.id,
                     "stage_id": self.env["crm.stage"].search([("is_won", "=", True)], limit=1).id})
        Lead.create({"name": "Лид из почты 25", "type": "lead", "partner_id": company.id})
        Lead.create({"name": "Проиграна 25", "type": "opportunity", "partner_id": company.id,
                     "active": False})
        company = company.with_user(self.admin)
        self.assertEqual(company.pmk_deal_count, 2,
                         "Сделка контактного лица и выигранная; лид и проигранная — нет.")
        self.assertEqual(person.with_user(self.admin).pmk_deal_count, 1)
        # Штатный счётчик ядра по-прежнему считает всё. Кнопка «Сделки» в
        # карточке с шага 28 показывает наш (test_step28_card.py).
        self.assertEqual(company.opportunity_count, 4)

    def test_standard_list_untouched(self):
        arch = self._arch(self.env.ref("base.view_partner_tree").id)
        self.assertTrue(arch.xpath("//field[@name='avatar_128']"),
                        "Штатный вид остаётся для других мест.")
        self.assertLess(self.env.ref("base.view_partner_tree").priority, self.view.priority,
                        "Наш вид не становится списком контрагентов по умолчанию.")
