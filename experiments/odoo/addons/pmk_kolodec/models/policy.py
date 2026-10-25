# -*- coding: utf-8 -*-
"""Ценовая политика (pmk_bolt) — вид изделий «Металлоизделия колодцев»."""
from odoo import fields, models


class PricePolicyLine(models.Model):
    _inherit = "pmk.price.policy.line"

    kind = fields.Selection(selection_add=[("kolodec", "Металлоизделия колодцев")], ondelete={"kolodec": "cascade"})
