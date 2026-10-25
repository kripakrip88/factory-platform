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


class CrmLeadFlowCount(models.Model):
    _name = "crm.lead"
    _inherit = ["crm.lead", "pmk.flow.count.mixin"]


class MetalSpecFlowCount(models.Model):
    _name = "pmk.metal.spec"
    _inherit = ["pmk.metal.spec", "pmk.flow.count.mixin"]


class LaserJobFlowCount(models.Model):
    _name = "pmk.laser.job"
    _inherit = ["pmk.laser.job", "pmk.flow.count.mixin"]


class LaserTaskFlowCount(models.Model):
    _name = "pmk.laser.task"
    _inherit = ["pmk.laser.task", "pmk.flow.count.mixin"]


class LaserNestFlowCount(models.Model):
    _name = "pmk.laser.nest"
    _inherit = ["pmk.laser.nest", "pmk.flow.count.mixin"]


class CutPlanFlowCount(models.Model):
    _name = "pmk.cut.plan"
    _inherit = ["pmk.cut.plan", "pmk.flow.count.mixin"]


class PurchaseOrderFlowCount(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "pmk.flow.count.mixin"]


class MrpProductionFlowCount(models.Model):
    _name = "mrp.production"
    _inherit = ["mrp.production", "pmk.flow.count.mixin"]


class AccountMoveFlowCount(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "pmk.flow.count.mixin"]


class StockPickingFlowCount(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "pmk.flow.count.mixin"]
