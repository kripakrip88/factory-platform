# -*- coding: utf-8 -*-
"""Маркетинговые метки (кампания, канал, источник) — разбор UX, шаг 29.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Разметка — собранная,
как её получает браузер (get_views: все наследники применены).

Что ловим: виды шага живы; группировки и поля поиска по UTM спрятаны во
всех поисках сделок и лидов, включая «Прогноз» (он собирается из поиска
сделок); колонки UTM в списке лидов и «Анализе лидов» убраны и из ⚙; своя
группировка «Откуда пришёл» на месте.
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged

HIDDEN = ("1", "True", "true")
UTM_FIELDS = ("campaign_id", "medium_id", "source_id")
# «compaign» — опечатка в имени у самого ядра.
UTM_FILTERS = ("compaign", "medium", "source")


def hidden(node, attr="invisible"):
    return (node.get(attr) or "").strip() in HIDDEN


@tagged("post_install", "-at_install")
class TestDealUtmStep29(TransactionCase):

    def _arch(self, xmlid, view_type):
        views = self.env["crm.lead"].get_views([(self.env.ref(xmlid).id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def test_views_active(self):
        for xmlid in ("pmk_deal.view_crm_opportunities_search_step29",
                      "pmk_deal.view_crm_leads_search_step29",
                      "pmk_deal.view_crm_report_search_step29",
                      "pmk_deal.view_crm_leads_list_utm_step29"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_search_group_by_hidden(self):
        searches = ["crm.view_crm_case_opportunities_filter", "crm.view_crm_case_leads_filter",
                    "crm.crm_opportunity_report_view_search"]
        if self.env.ref("crm.crm_lead_view_search_forecast", raise_if_not_found=False):
            searches.append("crm.crm_lead_view_search_forecast")
        for xmlid in searches:
            arch = self._arch(xmlid, "search")
            for name in UTM_FILTERS:
                with self.subTest(view=xmlid, filter=name):
                    nodes = arch.xpath("//filter[@name='%s']" % name)
                    self.assertTrue(nodes, "Узел на месте — на него ссылаются чужие xpath.")
                    self.assertTrue(all(hidden(node) for node in nodes))
            for name in UTM_FIELDS:
                with self.subTest(view=xmlid, field=name):
                    # Поле поиска бывает и внутри <group> («Анализ воронки»).
                    self.assertTrue(all(hidden(node) for node in arch.xpath("//field[@name='%s']" % name)))

    def test_own_source_group_by_stays(self):
        arch = self._arch("crm.view_crm_case_opportunities_filter", "search")
        nodes = arch.xpath("//filter[@name='groupby_pmk_source']")
        self.assertEqual(len(nodes), 1)
        self.assertFalse(hidden(nodes[0]))

    def test_leads_list_columns(self):
        for xmlid in ("crm.crm_case_tree_view_leads", "crm.crm_lead_view_tree_reporting"):
            arch = self._arch(xmlid, "list")
            for name in UTM_FIELDS:
                with self.subTest(view=xmlid, field=name):
                    nodes = arch.xpath("/list/field[@name='%s']" % name)
                    self.assertEqual(len(nodes), 1)
                    self.assertTrue(hidden(nodes[0], "column_invisible"))
