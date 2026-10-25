# -*- coding: utf-8 -*-
from odoo import fields


def post_init_hook(env):
    """Счета берём с даты установки модуля (раньше — только по решению Антона, параметром
    pmk_supplier_invoice.since); проверяющий — тот же, что у разбора почты (Голубенко).
    Отбор почты включён сразу (Антон 25.10: «для постоянного обновления цен»); на копии
    почта не качается — включение ничего не делает."""
    params = env["ir.config_parameter"].sudo()
    if not params.get_param("pmk_supplier_invoice.enabled"):
        params.set_param("pmk_supplier_invoice.enabled", "1")
    if not params.get_param("pmk_supplier_invoice.since"):
        params.set_param("pmk_supplier_invoice.since", fields.Datetime.to_string(fields.Datetime.now()))
