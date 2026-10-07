# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    pmk_source = fields.Selection(
        selection_add=[("telegram", "Телеграм")],
        ondelete={"telegram": "set null"})
