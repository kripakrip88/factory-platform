# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettingsAiMail(models.TransientModel):
    _inherit = "res.config.settings"

    pmk_ai_mail_enabled = fields.Boolean("Разбирать входящую почту", config_parameter="pmk_ai_mail.enabled")
    pmk_ai_mail_account = fields.Char("Ящик", config_parameter="pmk_ai_mail.account", default="pmkpark@mail.ru")
    pmk_ai_mail_user_id = fields.Many2one("res.users", "Проверяющий (менеджер сделок)",
                                          config_parameter="pmk_ai_mail.user_id")
    pmk_ai_mail_since = fields.Char("Разбирать письма с", config_parameter="pmk_ai_mail.since",
                                    help="Дата и время (UTC), с которых письма идут в разбор: «2026-10-21 00:00:00».")
