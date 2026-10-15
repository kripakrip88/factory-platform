# -*- coding: utf-8 -*-
"""19.0.0.7.0 — лист в «Купить» целыми листами раскладки (15.10.2026).

Новое хранимое поле pmk_layout_share ядро посчитает при обновлении, а
«Купить» и закупку строк по нему — нет (зависимые от нового поля при
обновлении не будятся; та же грабля, что у pmk_cut_cost). Пересчитываем
строки листа с раскладкой и будим изделия, итоги расчёта и маржу.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["pmk.metal.spec.line"].search([("calc_mode", "=", "sheet"), ("layout_group_id", "!=", False)])
    if not lines:
        return
    env.add_to_compute(lines._fields["pmk_layout_share"], lines)
    env.flush_all()
    names = ["cost_fact_one", "cost_fact_total", "weight_fact_one", "weight_fact_total"]
    for name in names:
        env.add_to_compute(lines._fields[name], lines)
    env.flush_all()
    lines.modified(names)
    env.flush_all()
