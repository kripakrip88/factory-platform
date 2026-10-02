# -*- coding: utf-8 -*-
"""Доборка на «Связях» сделки — доводка шага 35 разбора UX (02.10.2026).

Шаг 35 связал доборку со сделкой (pmk_deal: поле «Сделка» у доборки,
счётчик «Доборки» на сделке), а схема сделки доборки не знала: над формой
«Доборки 1», на вкладке «Связи» — пусто. Теперь доборка — этап «Доборка»
рядом с раскроем и лазером, связь в обе стороны.

Гонять ТОЛЬКО на одноразовой базе (см. tests/__init__.py).
"""
from odoo.tests import TransactionCase, tagged

from ..models.flow_builder import _STAGES


@tagged("post_install", "-at_install")
class TestDoborNodeStep35(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context, tracking_disable=True,
            mail_create_nolog=True, mail_create_nosubscribe=True))
        cls.client = cls.env["res.partner"].create({
            "name": "ООО «Кровля-ДВ» (тест 35)", "is_company": True})
        cls.deal = cls.env["crm.lead"].create({
            "name": "Навес на Ленина (тест 35)", "type": "opportunity",
            "partner_id": cls.client.id})
        cls.dobor = cls.env["pmk.dobor.order"].create({
            "opportunity_id": cls.deal.id, "partner_id": cls.client.id,
            "customer": "навес"})
        cls.Builder = cls.env["pmk.flow.builder"]

    def _nodes(self, model, res_id):
        graph = self.Builder.get_flow_graph(model, res_id)
        return {node["id"]: node for node in graph["nodes"]}, graph["edges"]

    def test_stage_next_to_cut_and_laser(self):
        self.assertEqual(_STAGES["pmk.dobor.order"], (4, "Доборка"))
        self.assertEqual(_STAGES["pmk.dobor.order"][0], _STAGES["pmk.cut.plan"][0],
                         "Работа цеха — в одной колонке с раскроем и лазером.")

    def test_deal_shows_its_dobor(self):
        self.assertEqual(self.deal.dobor_count, 1, "Счётчик над формой — 1.")
        nodes, edges = self._nodes("crm.lead", self.deal.id)
        key = "pmk.dobor.order,%s" % self.dobor.id
        self.assertIn(key, nodes, "На «Связях» сделки — та же доборка.")
        node = nodes[key]
        self.assertEqual(node["label"], self.dobor.name, "Номер ДОБ- целиком.")
        self.assertEqual(node["kind"], "Доборка")
        self.assertEqual(node["stage"], 4)
        self.assertEqual((node["state"], node["color"]), ("Черновик", "grey"))
        self.assertIn(self.client.display_name, node["hint"])
        self.assertEqual((node["open_model"], node["open_res_id"]),
                         ("pmk.dobor.order", self.dobor.id), "Клик открывает доборку.")
        self.assertIn({"from": "crm.lead,%s" % self.deal.id, "to": key}, edges)

    def test_dobor_leads_back_to_deal(self):
        nodes, _edges = self._nodes("pmk.dobor.order", self.dobor.id)
        self.assertIn("crm.lead,%s" % self.deal.id, nodes)

    def test_state_colors(self):
        for state, label, color in (("confirmed", "В работе", "blue"),
                                    ("done", "Изготовлен", "green")):
            with self.subTest(state=state):
                self.dobor.state = state
                node = self._nodes("crm.lead", self.deal.id)[0][
                    "pmk.dobor.order,%s" % self.dobor.id]
                self.assertEqual((node["state"], node["color"]), (label, color))
