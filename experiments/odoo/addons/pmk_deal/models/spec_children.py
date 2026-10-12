# -*- coding: utf-8 -*-
"""Сделка расчёта — в черновик доборки его категории (12.10.2026). У вентзонтов поля
сделки нет: они видны на сделке через расчёт."""
from odoo import models


class MetalSpecChildrenDeal(models.Model):
    _inherit = "pmk.metal.spec"

    def _pmk_child_vals(self, model):
        vals = super()._pmk_child_vals(model)
        if model == "pmk.dobor.order" and self.opportunity_id:
            vals["opportunity_id"] = self.opportunity_id.id
        return vals

    def write(self, vals):
        res = super().write(vals)
        if "opportunity_id" in vals:
            for spec in self:
                spec.dobor_order_ids.write({"opportunity_id": spec.opportunity_id.id})
        return res
