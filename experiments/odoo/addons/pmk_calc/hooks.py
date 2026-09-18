# -*- coding: utf-8 -*-
"""Заполнение металла у доборок, заведённых до появления справочника.

Поле «Металл» добавлено позже, когда толщина переехала в общий справочник.
Обязательным на уровне модели его сделать нельзя — обновление упало бы на
существующих строках, поэтому связь проставляется здесь, по толщине.
"""

from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    if not isinstance(env, api.Environment):     # совместимость со старой сигнатурой
        env = api.Environment(env, SUPERUSER_ID, {})

    lines = env["pmk.dobor.order.line"].search([("sheet_id", "=", False)])
    if not lines:
        return

    sheets = env["pmk.metal.sheet"]
    filled = 0
    for line in lines:
        sheet = sheets.search([("thickness_mm", "=", line.thickness)],
                              order="sheet_type", limit=1)
        if sheet:
            line.sheet_id = sheet.id
            filled += 1
    env["ir.logging"].sudo().create({
        "name": "pmk_calc", "type": "server", "level": "INFO",
        "dbname": env.cr.dbname, "message": f"Металл проставлен у {filled} доборок",
        "path": "pmk_calc.hooks", "func": "post_init_hook", "line": "0",
    })
