# -*- coding: utf-8 -*-
"""Число связанных документов — в заголовке вкладки «Связи» (Антон 25.10.2026).

Шапка документа «вариант А»: кнопки-счётчики связей (расчёт, заказ, технический
расчёт…) из шапки убраны — «у нас есть глобальная вкладка связи, вот проще ей и
пользоваться, просто добавить в заголовок вкладки счётчик связанных документов».
Число — узлы той же схемы, что рисует вкладка (get_flow_graph), без самого
документа. Не хранится: связи меняются в других документах. Схема строится за
0,02–0,23 с (замер на копии 25.10, счета 01216/01218/S00040).
Заголовок — static/src/flow_tab_count.js.
"""
from odoo import fields, models


class PmkFlowCountMixin(models.AbstractModel):
    _name = "pmk.flow.count.mixin"
    _description = "Счётчик вкладки «Связи»"

    pmk_flow_count = fields.Integer("Связанных документов", compute="_compute_pmk_flow_count")

    def _compute_pmk_flow_count(self):
        builder = self.env["pmk.flow.builder"]
        for record in self:
            if not isinstance(record.id, int):
                record.pmk_flow_count = 0
                continue
            graph = builder.get_flow_graph(record._name, record.id)
            record.pmk_flow_count = max(len(graph.get("nodes") or []) - 1, 0)


class SaleOrderFlowCount(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "pmk.flow.count.mixin"]
