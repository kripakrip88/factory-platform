# -*- coding: utf-8 -*-
"""Карточка клиента → «Расчёты» (разбор UX, шаг 28, 01.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Ловим: кто чьи
расчёты, что открывает кнопка, где она стоит и кому видна при нуле. Серый
ноль (stat_buttons.js темы) и вид кнопки — глазами на копии.
"""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestPartnerSpecs(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        # «Сделки» видит продавец — без группы якоря кнопки в разметке нет.
        cls.admin.write({"group_ids": [Command.link(
            cls.env.ref("sales_team.group_sale_salesman").id)]})
        Partner = cls.env["res.partner"]
        cls.company = Partner.create({"name": "ООО «Клиент 28»", "is_company": True})
        cls.person = Partner.create({"name": "Иван (клиент 28)", "parent_id": cls.company.id})
        cls.other = Partner.create({"name": "ООО «Другой 28»", "is_company": True})
        Spec = cls.env["pmk.metal.spec"]
        cls.spec_company = Spec.create({"partner_id": cls.company.id})
        cls.spec_with_contact = Spec.create({"partner_id": cls.company.id,
                                             "contact_id": cls.person.id})
        # Расчёт старого вида (до шага 11): клиентом записан сам человек.
        cls.spec_old = Spec.create({"partner_id": cls.person.id})
        cls.spec_other = Spec.create({"partner_id": cls.other.id})

    def test_count(self):
        self.assertEqual(self.company.pmk_spec_count, 3,
                         "Свои, с контактным лицом и старого вида на человека.")
        self.assertEqual(self.person.pmk_spec_count, 2,
                         "Где человек — клиент или контактное лицо.")
        self.assertEqual(self.other.pmk_spec_count, 1)
        fresh = self.env["res.partner"].create({"name": "ООО «Новый 28»", "is_company": True})
        self.assertEqual(fresh.pmk_spec_count, 0)

    def test_action_lists_client_specs(self):
        action = self.company.action_pmk_view_specs()
        self.assertEqual(action["res_model"], "pmk.metal.spec")
        self.assertEqual(action["name"], "Расчёты")
        self.assertEqual([mode for _view, mode in action["views"]][:1], ["list"],
                         "Всегда список — даже из одной строки.")
        found = self.env["pmk.metal.spec"].search(action["domain"])
        self.assertEqual(found, self.spec_company | self.spec_with_contact | self.spec_old)
        self.assertEqual(action["context"], {"default_partner_id": self.company.id})

    def test_action_from_person_defaults(self):
        """Новый расчёт с карточки человека: клиент — его компания, он сам —
        контактное лицо (как «Расчёт и КП» со сделки, шаг 11)."""
        action = self.person.action_pmk_view_specs()
        self.assertEqual(action["context"], {"default_partner_id": self.company.id,
                                             "default_contact_id": self.person.id})
        found = self.env["pmk.metal.spec"].search(action["domain"])
        self.assertEqual(found, self.spec_with_contact | self.spec_old)

    def _form(self):
        view_id = self.env.ref("base.view_partner_form").id
        views = self.env["res.partner"].with_user(self.admin).get_views([(view_id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_button_after_deals(self):
        arch = self._form()
        box = arch.xpath("//div[@name='button_box']")[0]
        names = [button.get("name") for button in box.iter("button")]
        self.assertIn("action_pmk_view_specs", names)
        self.assertEqual(names.index("action_pmk_view_specs"),
                         names.index("action_view_opportunity") + 1,
                         "«Расчёты» — сразу за «Сделками».")
        button = arch.xpath("//button[@name='action_pmk_view_specs']")[0]
        # Группы в собранной разметке ядро уже разобрало — смотрим сам вид.
        own = etree.fromstring(self.env.ref("pmk_deal.view_partner_form_specs_button").arch)
        self.assertFalse(own.xpath("//button[@name='action_pmk_view_specs']")[0].get("groups"),
                         "Расчёты читает любой сотрудник — группы на кнопке нет.")
        count = button.xpath("./field[@name='pmk_spec_count']")[0]
        self.assertEqual(count.get("widget"), "statinfo")
        self.assertEqual(count.get("string"), "Расчёты")

    def test_button_visibility(self):
        """Наш шаг — у клиента всегда (ноль серым), у остальных — когда есть."""
        expression = self._form().xpath(
            "//button[@name='action_pmk_view_specs']")[0].get("invisible")

        def hidden(**values):
            context = {"pmk_is_supplier": False, "user_ids": [], "ref_company_ids": [],
                       "pmk_spec_count": 0}
            context.update(values)
            return safe_eval(expression, context)

        self.assertFalse(hidden(), "Клиент без расчётов — «Расчёты 0» видно.")
        self.assertFalse(hidden(pmk_spec_count=2))
        self.assertTrue(hidden(pmk_is_supplier=True), "Поставщик без расчётов — кнопки нет.")
        self.assertFalse(hidden(pmk_is_supplier=True, pmk_spec_count=1))
        self.assertTrue(hidden(user_ids=[2]), "Пользователь системы — не клиент.")
        self.assertTrue(hidden(ref_company_ids=[1]), "Своя компания — не клиент.")
        # Кто поставщик — общий признак моста (pmk_bridge, шаг 28), тот же,
        # что у блоков «Продажи» / «Закупка»: с ним у контактного лица
        # поставщика нет «Расчётов 0».
        supplier = self.env["res.partner"].create({"name": "ООО «Поставщик 28»",
                                                   "is_company": True, "supplier_rank": 1})
        man = self.env["res.partner"].create({"name": "Менеджер поставщика 28",
                                              "parent_id": supplier.id})
        for partner in (supplier, man):
            with self.subTest(partner=partner.name):
                self.assertTrue(hidden(pmk_is_supplier=partner.pmk_is_supplier,
                                       pmk_spec_count=partner.pmk_spec_count))
        self.assertFalse(hidden(pmk_is_supplier=self.person.pmk_is_supplier,
                                pmk_spec_count=0),
                         "Контактное лицо клиента — «Расчёты 0» видно.")

    def test_view_active(self):
        self.assertTrue(self.env.ref("pmk_deal.view_partner_form_specs_button").active)
