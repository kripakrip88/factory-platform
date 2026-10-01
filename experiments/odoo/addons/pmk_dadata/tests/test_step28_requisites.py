# -*- coding: utf-8 -*-
"""«Реквизиты» и вкладка бухгалтерии контакта — разбор UX, шаг 28.

Разметка — собранная, как её получает браузер (get_views). Глазами это не
заменяет: положение кнопки «Заполнить по ИНН» и пустоту вкладки смотрит
основной агент в браузере на копии. Ловим то, что ломается молча:
  • «Состояние по ЕГРЮЛ» — только когда статус есть;
  • в строке ИНН сначала поле, потом кнопка (стиль ставит кнопку вплотную);
  • подсказки сайта и меток — про завод, а не про Odoo;
  • вкладка «Выставление счетов» контакта — тому же, кому и вкладка
    компании: бухгалтеру.
"""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestRequisitesStep28(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.view_id = cls.env.ref("base.view_partner_form").id
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        base_user = cls.env.ref("base.group_user")
        # Счета видит, бухгалтерии нет — как у менеджера и снабженца завода.
        cls.clerk = Users.create({
            "name": "Менеджер (тест 28)", "login": "pmk28_clerk",
            "group_ids": [Command.set([base_user.id,
                                       cls.env.ref("account.group_account_invoice").id])],
        })
        cls.accountant = Users.create({
            "name": "Бухгалтер (тест 28)", "login": "pmk28_accountant",
            "group_ids": [Command.set([base_user.id,
                                       cls.env.ref("account.group_account_user").id])],
        })

    def _form(self, user=None):
        Partner = self.env["res.partner"].with_user(user or self.env.ref("base.user_admin"))
        views = Partner.get_views([(self.view_id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def _one(self, arch, xpath):
        nodes = arch.xpath(xpath)
        self.assertEqual(len(nodes), 1, xpath)
        return nodes[0]

    def test_status_only_when_filled(self):
        arch = self._form()
        status = self._one(arch, "//page[@name='pmk_requisites']//field[@name='pmk_dadata_status']")
        expression = status.get("invisible")
        self.assertEqual(expression, "not pmk_dadata_status")
        self.assertTrue(safe_eval(expression, {"pmk_dadata_status": False}))
        self.assertFalse(safe_eval(expression, {"pmk_dadata_status": "Действующая"}))

    def test_inn_row_field_then_button(self):
        arch = self._form()
        row = self._one(arch, "//page[@name='pmk_requisites']//div[contains("
                              "concat(' ', normalize-space(@class), ' '), ' pmk-inn-row ')]")
        children = [(node.tag, node.get("name")) for node in row if isinstance(node.tag, str)]
        self.assertEqual(children, [("field", "vat"), ("button", "action_pmk_fill_by_inn")])

    def test_hints_about_the_plant(self):
        arch = self._form()
        website = self._one(arch, "//page[@name='pmk_requisites']//field[@name='website']")
        self.assertEqual(website.get("placeholder"), "например, stroy-dv.ru")
        tags = self._one(arch, "//page[@name='pmk_requisites']//field[@name='category_id']")
        self.assertEqual(tags.get("placeholder"), "например, Генподрядчик, Постоянный, Госзаказ")
        # Ни одной копии этих полей с подсказкой Odoo (сайт и метки — и в
        # шапке до переноса, должность — в карточке и в окне контакта).
        for name in ("website", "category_id", "function"):
            for node in arch.xpath("//field[@name='%s'][@placeholder]" % name):
                placeholder = node.get("placeholder")
                with self.subTest(field=name, placeholder=placeholder):
                    for odoo_word in ("odoo.com", "B2B", "VIP", "Sales Director"):
                        self.assertNotIn(odoo_word, placeholder)

    def test_contact_accounting_tab_for_accountant_only(self):
        """Фраза «…управляются на материнская компания» — только тому, кто
        видит и саму вкладку компании (порог pmk_dadata)."""
        for user, expected in ((self.clerk, False), (self.accountant, True)):
            arch = self._form(user)
            with self.subTest(user=user.login):
                self.assertEqual(bool(arch.xpath("//page[@name='accounting_disabled']")), expected)
                self.assertEqual(bool(arch.xpath("//page[@name='accounting']")), expected)

    def test_view_active(self):
        self.assertTrue(self.env.ref("pmk_dadata.view_partner_form_requisites").active)
