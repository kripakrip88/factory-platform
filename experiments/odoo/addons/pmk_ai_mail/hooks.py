# -*- coding: utf-8 -*-
from odoo import fields


def post_init_hook(env):
    """Разбор — с момента установки (старые письма не трогаем), выключен до решения
    «включить» в настройках; проверяющий — Голубенко, если он есть."""
    params = env["ir.config_parameter"].sudo()
    if not params.get_param("pmk_ai_mail.since"):
        params.set_param("pmk_ai_mail.since", fields.Datetime.to_string(fields.Datetime.now()))
    if not params.get_param("pmk_ai_mail.user_id"):
        user = env["res.users"].sudo().search([("login", "=", "vladimir.golubenko")], limit=1)
        if user:
            params.set_param("pmk_ai_mail.user_id", str(user.id))
