# -*- coding: utf-8 -*-
"""Строка «Заказов в работе»: технический расчёт и заявки на металл (шаг З-4).

Планировщик — следующий шаг инженера после счёта: из строки заказа те же
кнопки, что в счёте, — «Технический расчёт» (завести или открыть) и «Заявка
на металл» (из технического расчёта). Строка без счёта (импорт из Excel) —
кнопок нет: технический расчёт снимается со счёта.

Счётчик «Заявки на металл» — заказы поставщику этой строки (pmk_task_id) или
её счёта; только «Закупкам».
"""
from odoo import api, fields, models


class ProjectTaskTech(models.Model):
    _inherit = "project.task"

    pmk_tech_spec_id = fields.Many2one(
        related="pmk_sale_order_id.pmk_tech_spec_id", string="Технический расчёт")
    pmk_metal_request_count = fields.Integer(
        "Заявки на металл", compute="_compute_pmk_metal_request_count",
        groups="purchase.group_purchase_user")

    def _pmk_metal_request_domain(self):
        self.ensure_one()
        domain = [("pmk_task_id", "=", self.id)]
        if self.pmk_sale_order_id:
            domain = ["|", ("pmk_sale_order_id", "=", self.pmk_sale_order_id.id)] + domain
        return domain

    @api.depends("pmk_sale_order_id")
    def _compute_pmk_metal_request_count(self):
        PO = self.env["purchase.order"]
        for task in self:
            if not isinstance(task.id, int) or not PO.has_access("read"):
                task.pmk_metal_request_count = 0
                continue
            task.pmk_metal_request_count = PO.search_count(
                task._pmk_metal_request_domain() + [("state", "!=", "cancel")])

    def action_pmk_tech_spec(self):
        self.ensure_one()
        return self.pmk_sale_order_id.action_pmk_tech_spec()

    def action_pmk_metal_request(self):
        self.ensure_one()
        tech = self.env["pmk.metal.spec"].browse(self.pmk_tech_spec_id.id)
        if not tech:
            return self.action_pmk_tech_spec()
        return tech.action_pmk_metal_request()

    def action_pmk_metal_requests(self):
        self.ensure_one()
        return self.env["purchase.order"]._pmk_requests_window(self._pmk_metal_request_domain())
