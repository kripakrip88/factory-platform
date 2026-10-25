# -*- coding: utf-8 -*-
"""Ценовая политика (pmk_bolt) — вид изделий «Опоры трубопроводов»."""
from odoo import fields, models


class PricePolicyLine(models.Model):
    _inherit = "pmk.price.policy.line"

    kind = fields.Selection(selection_add=[("opora", "Опоры трубопроводов")], ondelete={"opora": "cascade"})
