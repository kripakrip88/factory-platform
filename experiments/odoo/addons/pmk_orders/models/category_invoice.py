# -*- coding: utf-8 -*-
"""Черновик счёта идёт и за доборкой, и за вентзонтами расчёта (12.10.2026): поменяли
цену, количество, размер или цвет позиции — строки черновика пересобираются, как при
правке изделий расчёта (metal_spec.py)."""
from odoo import api, models

DOBOR_FIELDS = frozenset({"price_unit", "qty", "title", "plank_length", "coating_id", "sequence"})
VENT_FIELDS = frozenset({"price_unit", "qty", "width", "length", "coating_id", "sves", "sequence"})


def _specs(lines):
    return lines.mapped("order_id.spec_id")


class DoborLineInvoice(models.Model):
    _inherit = "pmk.dobor.order.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        _specs(lines)._pmk_sync_draft_invoices()
        return lines

    def write(self, vals):
        if not (DOBOR_FIELDS & set(vals)):
            return super().write(vals)
        res = super().write(vals)
        _specs(self)._pmk_sync_draft_invoices()
        return res

    def unlink(self):
        specs = _specs(self)
        res = super().unlink()
        specs._pmk_sync_draft_invoices()
        return res


class VentLineInvoice(models.Model):
    _inherit = "pmk.vent.hood"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        _specs(lines)._pmk_sync_draft_invoices()
        return lines

    def write(self, vals):
        if not (VENT_FIELDS & set(vals)):
            return super().write(vals)
        res = super().write(vals)
        _specs(self)._pmk_sync_draft_invoices()
        return res

    def unlink(self):
        specs = _specs(self)
        res = super().unlink()
        specs._pmk_sync_draft_invoices()
        return res
