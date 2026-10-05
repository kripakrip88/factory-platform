# -*- coding: utf-8 -*-
"""Один фильтр «В работе» в поиске сделок — разбор UX, шаг 39.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Разметка — собранная,
как её получает браузер (get_views: все наследники применены).

Что ловим: вид шага жив; «Сделки в работе» (open_opportunities) спрятан, но
узел на месте; «В работе» (filter_won_status_pending) виден — на него
ссылаются кнопка «Сделки» контрагента и окно перевода лида в сделку; оба
фильтра в воронке дают один и тот же набор (иначе прятать было нельзя).
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged

HIDDEN = ("1", "True", "true")


def hidden(node):
    return (node.get("invisible") or "").strip() in HIDDEN


@tagged("post_install", "-at_install")
class TestDealFiltersStep39(TransactionCase):

    def _arch(self, xmlid):
        views = self.env["crm.lead"].get_views([(self.env.ref(xmlid).id, "search")])
        return etree.fromstring(views["views"]["search"]["arch"])

    def test_view_active(self):
        self.assertTrue(self.env.ref("pmk_deal.view_crm_opportunities_search_step39").active)

    def test_one_filter_in_work(self):
        searches = ["crm.view_crm_case_opportunities_filter"]
        if self.env.ref("crm.crm_lead_view_search_forecast", raise_if_not_found=False):
            searches.append("crm.crm_lead_view_search_forecast")
        for xmlid in searches:
            arch = self._arch(xmlid)
            with self.subTest(view=xmlid, filter="open_opportunities"):
                nodes = arch.xpath("//filter[@name='open_opportunities']")
                self.assertTrue(nodes, "Узел на месте — спрятан, а не удалён.")
                self.assertTrue(all(hidden(node) for node in nodes))
            with self.subTest(view=xmlid, filter="filter_won_status_pending"):
                nodes = arch.xpath("//filter[@name='filter_won_status_pending']")
                self.assertEqual(len(nodes), 1)
                self.assertFalse(hidden(nodes[0]))

    def test_same_set_in_pipeline(self):
        """В воронке (только сделки) оба фильтра отбирают одно и то же."""
        partner = self.env["res.partner"].create({"name": "Шаг 39, клиент"})
        Lead = self.env["crm.lead"]
        deals = Lead.create([
            {"name": "В работе", "type": "opportunity", "partner_id": partner.id},
            {"name": "Выиграна", "type": "opportunity", "partner_id": partner.id},
            {"name": "Проиграна", "type": "opportunity", "partner_id": partner.id},
        ])
        deals[1].action_set_won()
        deals[2].action_set_lost()
        scope = [("type", "=", "opportunity"), ("partner_id", "=", partner.id)]
        open_opportunities = Lead.search(scope + [
            ("probability", "<", 100), ("type", "=", "opportunity"), ("active", "=", True)])
        in_work = Lead.search(scope + [("won_status", "=", "pending"), ("active", "=", True)])
        self.assertEqual(open_opportunities, in_work)
        self.assertEqual(in_work, deals[0])
