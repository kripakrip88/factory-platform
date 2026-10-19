# -*- coding: utf-8 -*-
"""19.0.0.9.1 — досчитать цену строкам, созданным формой без неё (19.10.2026).

Дефект: форма присылала цену единицы, ядро защищало всю вычисляемую группу, и
строка ложилась «Позиция не выбрана», без источника и цены за тонну — металл
строки считался нулём (боевая: 59 строк, 08–12.10). Новые строки чинит create
(spec_cost.py), здесь — уже лежащие. end-: стоимость дополняют pmk_cut_cost и
pmk_tech, они должны быть загружены.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True})
    lines = env["pmk.metal.spec.line"].search([("price_state", "=", "empty")])
    specs = lines.filtered(lambda l: l._cost_position()).spec_id
    before = {s.id: s.total_cost_fact for s in specs}
    fixed = lines._pmk_fill_lost_price()
    env.flush_all()
    for spec in specs:
        _logger.info("pmk_bridge 19.0.0.9.1: %s — закупка металла %.2f → %.2f",
                     spec.name, before[spec.id], spec.total_cost_fact)
    _logger.info("pmk_bridge 19.0.0.9.1: досчитано строк %s в %s расчётах; без цены после досчёта: %s",
                 len(fixed), len(specs), len(fixed.filtered(lambda l: l.price_state != "ok")))
