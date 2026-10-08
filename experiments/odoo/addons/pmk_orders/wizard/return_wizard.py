# -*- coding: utf-8 -*-
"""«Вернуть на доработку» — окно с комментарием руководителя (шаг З-9).

Комментарий обязателен: менеджер должен понять, что поправить. Он ложится
заметкой в ленту счёта и текстом задачи «Доработать счёт» менеджеру (без
письма). Права на окно — только у группы «Руководитель: согласует счета»
(security/ir.model.access.csv), и сервер проверяет группу ещё раз
(sale.order._pmk_return_to_rework).
"""
from odoo import fields, models


class PmkOrdersReturnWizard(models.TransientModel):
    _name = "pmk.orders.return.wizard"
    _description = "Вернуть счёт на доработку"

    order_id = fields.Many2one(
        "sale.order", "Счёт покупателю", required=True, ondelete="cascade")
    comment = fields.Text("Что поправить", required=True)

    def action_return(self):
        self.ensure_one()
        self.order_id._pmk_return_to_rework((self.comment or "").strip())
        return {"type": "ir.actions.act_window_close"}
