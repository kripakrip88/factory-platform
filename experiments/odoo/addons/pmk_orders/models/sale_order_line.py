# -*- coding: utf-8 -*-
"""Строка счёта покупателю ↔ изделие расчёта (шаг З-2).

Строка счёта — одно изделие расчёта: состав, вес и металл живут в расчёте,
строка помнит, из какого изделия она пришла. По этой связи редакция знает,
какие строки заменить заново из расчёта, а какие ручные (доставка, скидка) —
оставить. Строки прежней редакции (снимка) только для чтения.
"""
from odoo import api, fields, models

from .sale_order import freeze_allowed, snapshot_error


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    pmk_spec_product_id = fields.Many2one(
        "pmk.metal.spec.product", "Изделие расчёта", index=True,
        ondelete="set null", copy=False,
        help="Изделие расчёта, из которого пришла строка. Состав и вес — в расчёте.")
    # Отдельный признак, а не «есть изделие»: изделие удалили из расчёта —
    # ссылка обнулится (set null), а строка всё равно расчётная, и новая
    # редакция должна её заменить, а не оставить как ручную.
    pmk_from_spec = fields.Boolean(
        "Из расчёта", copy=False,
        help="Строка выставлена из расчёта: новая редакция заменит её заново. "
             "Ручные строки (доставка, скидка) редакция не трогает.")

    def _pmk_check_not_snapshot(self, orders=None):
        if freeze_allowed(self.env):
            return
        for order in (orders if orders is not None else self.order_id):
            if order.pmk_is_revision:
                raise snapshot_error(order)

    @api.model_create_multi
    def create(self, vals_list):
        if not freeze_allowed(self.env):
            ids = {vals["order_id"] for vals in vals_list if vals.get("order_id")}
            self._pmk_check_not_snapshot(self.env["sale.order"].browse(ids))
        return super().create(vals_list)

    def write(self, vals):
        self._pmk_check_not_snapshot()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _pmk_unlink_except_revision(self):
        self._pmk_check_not_snapshot()
