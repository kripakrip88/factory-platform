# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    mail_client_account_ids = fields.One2many(
        'mail.client.account', 'user_id', string='Mail Accounts',
    )
    mail_client_access_ids = fields.One2many(
        'mail.client.access', 'user_id', string='Shared Mailbox Access',
    )
