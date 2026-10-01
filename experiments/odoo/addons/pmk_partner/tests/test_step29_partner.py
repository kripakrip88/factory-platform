# -*- coding: utf-8 -*-
"""Контрагент: убрать совсем — разбор UX, шаг 29.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo (см. __init__.py).
Разметка — собранная, как её получает браузер (get_views).

Что ловим:
  • виды шага живы (упавший xpath Odoo выключает при загрузке молча);
  • в поиске нет группировки «Страна» и фильтра «Сотрудники», соседи на
    месте; группа «Убранное (показать)» возвращает оба;
  • «Тип адреса» в окне контактного лица — наш виджет со списком скрытых
    «Счет» и «Прочее», а сами варианты поля в модели целы (данные не
    ломаются);
  • новое контактное лицо — «Контакт» и у организации, и у ИП / физлица
    (ядро ставило физлицу скрытое «Прочее»); остальные ключи контекста —
    как у вида ядра;
  • «Клиенты» — список и форма, без канбана; в базе действие не тронуто,
    «Поставщики» не тронуты;
  • виджет в бандле, правила — раньше виджета.

Сам переключатель (видно четыре варианта, у старой записи «Прочее» —
отмеченным) — правило js/radio_hide_rules.js гоняет node, глазами смотрит
основной агент.
"""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

REMOVED = "pmk_theme.group_pmk_removed"
JS = "pmk_partner/static/src/js/"


@tagged("post_install", "-at_install")
class TestPartnerStep29(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("base.group_partner_manager").id),
            Command.link(cls.env.ref("sales_team.group_sale_manager").id),
            Command.link(cls.env.ref("hr.group_hr_user").id),
        ]})

    def _arch(self, view_type="form", view_xmlid=None):
        view_id = self.env.ref(view_xmlid).id if view_xmlid else False
        views = self.env["res.partner"].with_user(self.admin).get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def test_views_active(self):
        for xmlid in ("pmk_partner.view_partner_search_step29",
                      "pmk_partner.view_partner_search_employees_step29",
                      "pmk_partner.view_partner_form_address_type_step29"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_search(self):
        arch = self._arch("search", "base.view_res_partner_filter")
        self.assertFalse(arch.xpath("//filter[@name='group_country']"))
        self.assertFalse(arch.xpath("//filter[@name='employees']"))
        for name in ("salesperson", "group_company", "supplier", "inactive"):
            with self.subTest(kept=name):
                self.assertTrue(arch.xpath("//filter[@name='%s']" % name))

    def test_search_reversible(self):
        self.admin.write({"group_ids": [Command.link(self.env.ref(REMOVED).id)]})
        arch = self._arch("search", "base.view_res_partner_filter")
        self.assertTrue(arch.xpath("//filter[@name='group_country']"))
        self.assertTrue(arch.xpath("//filter[@name='employees']"))

    def test_address_type_widget(self):
        arch = self._arch("form", "base.view_partner_form")
        nodes = arch.xpath("//field[@name='child_ids']/form//field[@name='type']")
        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertEqual(node.get("widget"), "pmk_radio_hide")
        # Опции вида — в записи браузера (true строчными, как у ядра).
        options = safe_eval(node.get("options"), {"true": True, "false": False})
        self.assertEqual(options, {"horizontal": True, "pmk_hide": ["invoice", "other"]})
        # Варианты поля в модели целы — прячет только экран.
        values = [value for value, _label in self.env["res.partner"]._fields["type"].selection]
        for value in ("contact", "invoice", "delivery", "other"):
            with self.subTest(value=value):
                self.assertIn(value, values)

    def test_new_contact_type_is_contact(self):
        """«Добавить» в контактах ИП / физлица: ядро ставило «Прочее» —
        скрытый вариант стоял бы отмеченным и попадал в базу. Теперь
        «Контакт», а остальные умолчания — слово в слово как у ядра (если
        ядро их поменяет, тест скажет переписать контекст)."""
        nodes = self._arch("form", "base.view_partner_form").xpath("//field[@name='child_ids']")
        self.assertEqual(len(nodes), 1)
        core = etree.fromstring(self.env.ref("base.view_partner_form").arch)
        core_nodes = core.xpath("//field[@name='child_ids']")
        self.assertEqual(len(core_nodes), 1)
        names = {
            "id": 7, "street": "ул. Заводская, 1", "street2": False, "city": "Хабаровск",
            "state_id": 3, "zip": "680000", "country_id": 4, "lang": "ru_RU", "user_id": 2,
        }
        for is_company in (True, False):
            with self.subTest(is_company=is_company):
                scope = dict(names, is_company=is_company)
                ours = safe_eval(nodes[0].get("context"), dict(scope))
                theirs = safe_eval(core_nodes[0].get("context"), dict(scope))
                self.assertEqual(ours.pop("default_type"), "contact")
                self.assertEqual(theirs.pop("default_type"), "contact" if is_company else "other",
                                 "Предпосылка теста: у ядра физлицу — «Прочее».")
                self.assertEqual(ours, theirs, "Остальные ключи — как у ядра.")

    def test_customers_list_and_form(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("account.res_partner_action_customer")
        self.assertEqual([mode for _id, mode in action["views"]], ["list", "form"])
        self.assertEqual(action["view_mode"], "list,form")
        # Свой список «Клиенты» шага 25 — первым.
        self.assertEqual(action["views"][0][0], self.env.ref("pmk_partner.view_partner_customer_list").id)
        self.assertIn("kanban", self.env.ref("account.res_partner_action_customer").view_mode,
                      "В базе действие не тронуто.")
        suppliers = self.env["ir.actions.act_window"]._for_xml_id("account.res_partner_action_supplier")
        self.assertIn("kanban", suppliers["view_mode"], "«Поставщики» шаг 29 не трогает.")

    def test_widget_in_bundle(self):
        paths = [entry[0].lstrip("/") for entry in
                 self.env["ir.asset"]._get_asset_paths("web.assets_backend", {})]
        for name in ("radio_hide_rules.js", "radio_hide_field.js"):
            with self.subTest(file=name):
                self.assertIn(JS + name, paths)
        self.assertLess(paths.index(JS + "radio_hide_rules.js"), paths.index(JS + "radio_hide_field.js"))
        self.assertLess(paths.index("web/static/src/views/fields/radio/radio_field.js"),
                        paths.index(JS + "radio_hide_field.js"))
