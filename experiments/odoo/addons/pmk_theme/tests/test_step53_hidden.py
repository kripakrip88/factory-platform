# -*- coding: utf-8 -*-
"""Спрятать до востребования — разбор UX, шаг 53 (приёмка 07.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Разметка — как её
получает браузер (get_views: все наследники применены, узлы чужих групп
вырезаны сервером).

Что ловим:
  • теги сделки и лида — нет в форме (оба узла: лида и сделки), в списках
    сделок и лидов, в канбане воронки и в поиске — у менеджера продаж и
    закупок и у admin без группы;
  • «Снабженец» (buyer_id) в карточке контрагента — нет;
  • доборка: в окне позиции нет ширины рулона, полос и отхода, в списке
    позиций — полос и отхода; служебная колонка ширины рулона в списке
    позиций на месте (её берёт «Копировать»);
  • группа «Убранное (показать)» возвращает каждый узел — правило бьёт в
    существующий узел, а не в пустоту;
  • данные не тронуты: позиция доборки с рулоном после чтения формы та же;
    подпись «Снабженец» у узла сохранилась (вернётся вместе с ним);
  • форма сделки собирается без ошибок у менеджера (на теги сделки не
    ссылается ни один модификатор и контекст её разметки; «default_tag_ids»
    sale_crm — теги КП в форме КП, не сделки).

Глазами (сделка, лид, воронка, карточка поставщика, окно позиции доборки,
⚙ колонок списка позиций; светлая и тёмная тема) — основной агент.
"""
import json

from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.pmk_theme.models.hidden_nodes import HIDDEN_NODES

REMOVED = "pmk_theme.group_pmk_removed"
HIDDEN = ("1", "True", "true")
# Чертёж позиции — тот же, что в pmk_calc/tests/test_dobor_copy.py.
SNAPSHOT = json.dumps({
    "start": {"x": 0, "y": 0},
    "segs": [{"len": 85, "dir": 0}, {"len": 61, "dir": 90}, {"len": 20, "dir": 180}],
    "hemLeft": True, "hemLen": 10,
})

# (модель, xml-id вида или None, тип) → xpath узлов, которых не должно быть.
CASES = [
    ("crm.lead", "crm.crm_lead_view_form", "form", "//field[@name='tag_ids'][not(ancestor::field)]"),
    ("crm.lead", "crm.crm_case_tree_view_oppor", "list", "//field[@name='tag_ids']"),
    ("crm.lead", "crm.crm_case_tree_view_leads", "list", "//field[@name='tag_ids']"),
    ("crm.lead", "crm.crm_case_kanban_view_leads", "kanban", "//field[@name='tag_ids']"),
    ("crm.lead", "crm.view_crm_case_opportunities_filter", "search", "//field[@name='tag_ids']"),
    ("crm.lead", "crm.view_crm_case_leads_filter", "search", "//field[@name='tag_ids']"),
    ("res.partner", "base.view_partner_form", "form", "//field[@name='buyer_id'][not(ancestor::field)]"),
    ("pmk.dobor.order", None, "form", "//field[@name='line_ids']/form//field[@name='coil_width']"),
    ("pmk.dobor.order", None, "form", "//field[@name='line_ids']/form//field[@name='strips']"),
    ("pmk.dobor.order", None, "form", "//field[@name='line_ids']/form//field[@name='strip_waste']"),
    ("pmk.dobor.order", None, "form", "//field[@name='line_ids']/list/field[@name='strips']"),
    ("pmk.dobor.order", None, "form", "//field[@name='line_ids']/list/field[@name='strip_waste']"),
]


def shown(arch, expr):
    """Узлы, которые человек увидит (поля, досозданные ядром невидимыми, — нет)."""
    return [node for node in arch.xpath(expr)
            if (node.get("invisible") or "").strip() not in HIDDEN
            and (node.get("column_invisible") or "").strip() not in HIDDEN]


@tagged("post_install", "-at_install")
class TestHiddenStep53(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("sales_team.group_sale_manager").id),
            Command.link(cls.env.ref("purchase.group_purchase_manager").id),
            Command.unlink(cls.env.ref(REMOVED).id),
        ]})
        cls.manager = new_test_user(
            cls.env, login="pmk53_manager",
            groups="base.group_user,sales_team.group_sale_salesman,purchase.group_purchase_user")

    def _arch(self, model, xmlid, view_type, user):
        if model not in self.env:
            self.skipTest("%s не установлен" % model)
        view = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else None
        if xmlid and not view:
            self.skipTest("нет вида %s" % xmlid)
        views = self.env[model].with_user(user).get_views([(view.id if view else False, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _join(self):
        self.admin.write({"group_ids": [Command.link(self.env.ref(REMOVED).id)]})

    def test_rules_registered(self):
        expected = {("crm.lead", "form"), ("crm.lead", "list"), ("crm.lead", "kanban"),
                    ("crm.lead", "search"), ("res.partner", "form"), ("pmk.dobor.order", "form")}
        self.assertLessEqual(expected, set(HIDDEN_NODES))
        for key in expected:
            for _expr, group in HIDDEN_NODES[key]:
                with self.subTest(rule=key):
                    self.assertEqual(group, REMOVED, "До востребования — «Убранное (показать)».")

    def test_hidden_for_everyone_without_group(self):
        for user in (self.manager, self.admin):
            for model, xmlid, view_type, expr in CASES:
                with self.subTest(user=user.login, view=xmlid or model, node=expr):
                    arch = self._arch(model, xmlid, view_type, user)
                    self.assertFalse(shown(arch, expr))

    def test_group_brings_every_node_back(self):
        """Правило бьёт в существующий узел, а не в пустоту."""
        self._join()
        for model, xmlid, view_type, expr in CASES:
            with self.subTest(view=xmlid or model, node=expr):
                arch = self._arch(model, xmlid, view_type, self.admin)
                self.assertTrue(arch.xpath(expr))
        # У сделки и у лида — по узлу тегов в форме.
        form = self._arch("crm.lead", "crm.crm_lead_view_form", "form", self.admin)
        self.assertEqual(len(form.xpath("//field[@name='tag_ids'][not(ancestor::field)]")), 2)
        partner = self._arch("res.partner", "base.view_partner_form", "form", self.admin)
        # подпись «Снабженец» даёт pmk_purchase — без него проверять нечего
        if "pmk.price.mailing" in self.env:
            node = partner.xpath("//group[@name='purchase']/field[@name='buyer_id']")[0]
            self.assertEqual(node.get("string"), "Снабженец",
                             "Подпись pmk_purchase вернётся вместе с узлом.")

    def test_copy_keeps_coil_width(self):
        """Служебная колонка ширины рулона — на месте: из неё «Копировать»
        берёт значение (dobor_copy_line.js)."""
        for user in (self.manager, self.admin):
            with self.subTest(user=user.login):
                arch = self._arch("pmk.dobor.order", None, "form", user)
                nodes = arch.xpath("//field[@name='line_ids']/list/field[@name='coil_width']")
                self.assertEqual(len(nodes), 1)
                self.assertIn(nodes[0].get("column_invisible"), HIDDEN)

    def test_deal_form_opens(self):
        """Форма сделки собирается у менеджера, тегов на ней не видно."""
        arch = self._arch("crm.lead", "crm.crm_lead_view_form", "form", self.manager)
        self.assertFalse(shown(arch, "//field[@name='tag_ids'][not(ancestor::field)]"))
        views = self.env["crm.lead"].with_user(self.manager).get_views([(False, "form")])
        self.assertIn("crm.lead", views["models"])

    def test_dobor_data_untouched(self):
        """Позиция с рулоном (как ДОБ-00001 на бою: 1250 мм) — значения
        хранятся и пересчитываются, как раньше; правка заказа их не теряет."""
        if "pmk.dobor.order" not in self.env:
            self.skipTest("pmk_calc не установлен")
        sheet = self.env["pmk.metal.sheet"].create({
            "sheet_type": "Оцинкованный", "thickness_mm": 0.7,
            "gost": "ГОСТ 14918-2020 (тест 53)", "mass_per_sqm": 5.495})
        coating = self.env["pmk.dobor.coating"].create({
            "name": "RAL 8017 (тест 53)", "ral_code": "8017", "hex_color": "#45322e"})
        order =self.env["pmk.dobor.order"].with_context(mail_create_nolog=True).create({
            "customer": "Тест 53",
            "line_ids": [Command.create({
                "title": "Отлив", "sheet_id": sheet.id, "coating_id": coating.id, "plank_length": 2500.0, "qty": 7,
                "coil_width": 1250.0, "profile_snapshot_json": SNAPSHOT,
            })],
        })
        line = order.line_ids
        before = (line.coil_width, line.strips, line.strip_waste)
        self.assertEqual(before[0], 1250.0)
        self.assertGreater(before[1], 0, "Полосы из рулона считаются по-прежнему.")
        # Как браузер: разметка формы менеджера без полей рулона, правка шапки
        # заказа — значения позиции остаются.
        arch = self._arch("pmk.dobor.order", None, "form", self.manager)
        self.assertFalse(shown(arch, "//field[@name='line_ids']/form//field[@name='coil_width']"))
        order.with_user(self.manager).web_save({"customer": "Тест 53, правка"}, {"customer": {}})
        self.env.invalidate_all()
        self.assertEqual((line.coil_width, line.strips, line.strip_waste), before)
        for model, name in (("pmk.dobor.order.line", "coil_width"), ("pmk.dobor.order.line", "strips"),
                            ("pmk.dobor.order.line", "strip_waste"), ("res.partner", "buyer_id"),
                            ("crm.lead", "tag_ids")):
            with self.subTest(field=name):
                self.assertTrue(self.env[model]._fields[name].store, "Поле на месте.")
