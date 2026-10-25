# -*- coding: utf-8 -*-
"""Болты расчётов (категория «Фундаментные болты») → изделия «Конструкций» (Антон 25.10.2026,
вариант 1). На боевом 25.10 — один расчёт с одним болтом, в счетах болтов нет."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for spec in env["pmk.metal.spec"].search([("cat_bolt", "=", True)]):
        for doc in spec.bolt_calc_ids:
            doc._pmk_to_konstr(spec)
        spec.cat_bolt = False
