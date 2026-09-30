# -*- coding: utf-8 -*-
"""Список сделок без кнопок «СМС» (разбор UX, шаг 31) — собранная разметка,
как её получает браузер (get_views: все наследники применены)."""
from lxml import etree

from odoo.tests import TransactionCase, tagged


def hidden(node):
    """Скрыт ли узел насовсем (invisible="1" — после сборки может стать True)."""
    return (node.get("invisible") or "").strip() in ("1", "True", "true")


@tagged("post_install", "-at_install")
class TestNoSms(TransactionCase):

    def _arch(self, view_xmlid):
        views = self.env["crm.lead"].get_views([(self.env.ref(view_xmlid).id, "list")])
        return etree.fromstring(views["views"]["list"]["arch"])

    def test_view_is_active(self):
        """Вид с упавшим xpath Odoo выключает при загрузке — ловим это."""
        self.assertTrue(self.env.ref("pmk_deal_sms.view_crm_lead_list_no_sms").active)

    def test_list_without_sms(self):
        arch = self._arch("crm.crm_case_tree_view_oppor")
        for xmlid in ("crm_sms.crm_lead_act_window_sms_composer_single",
                      "crm_sms.crm_lead_act_window_sms_composer_multi"):
            with self.subTest(action=xmlid):
                button = arch.find(".//button[@name='%s']" % self.env.ref(xmlid).id)
                self.assertIsNotNone(button, "Кнопка скрыта, а не удалена.")
                self.assertTrue(hidden(button))

    def test_reporting_list_still_builds(self):
        """Вид crm_sms над отчётным списком заменяет кнопку строки своим
        xpath'ом — без узла сборка упала бы."""
        self._arch("crm.crm_lead_view_tree_opportunity_reporting")

    def test_pmk_deal_does_not_depend_on_sms(self):
        """Удаление «SMS» / iap не должно каскадом сносить pmk_deal — ни
        прямой зависимостью, ни через цепочку."""
        names, todo = set(), self.env["ir.module.module"].search([("name", "=", "pmk_deal")])
        self.assertTrue(todo)
        while todo:
            deps = todo.dependencies_id.depend_id
            todo = deps.filtered(lambda module: module.name not in names)
            names |= set(deps.mapped("name"))
        self.assertIn("crm", names)
        self.assertFalse({"crm_sms", "sms", "iap_mail", "iap"} & names, sorted(names))
