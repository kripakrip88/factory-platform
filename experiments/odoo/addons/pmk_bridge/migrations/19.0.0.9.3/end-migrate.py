# -*- coding: utf-8 -*-
"""19.0.0.9.3 — шапка расчёта по всем категориям (Антон 22.10.2026: «да делаем всё»).

Цена клиенту, вес, число изделий — теперь с доборкой, зонтами и болтами; маржа — по
позициям с себестоимостью. Хранимые итоги уже лежащих расчётов пересчитываем, а с ними
(по зависимостям) — деньги и вес в сделках. end-: категории дописывают pmk_bolt и др.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True})
    specs = env["pmk.metal.spec"].with_context(active_test=False).search([])
    before = {s.id: (s.price_customer_total, s.total_weight) for s in specs}
    Spec = env["pmk.metal.spec"]
    specs.modified([f for f in ("cat_metal", "cat_dobor", "cat_vent", "cat_bolt") if f in Spec._fields])
    env.flush_all()
    changed = specs.filtered(lambda s: abs(before[s.id][0] - s.price_customer_total) >= 0.01
                             or abs(before[s.id][1] - s.total_weight) >= 0.01)
    for spec in changed:
        _logger.info("pmk_bridge 19.0.0.9.3: %s — цена клиенту %.2f → %.2f, вес %.1f → %.1f кг", spec.name,
                     before[spec.id][0], spec.price_customer_total, before[spec.id][1], spec.total_weight)
    _logger.info("pmk_bridge 19.0.0.9.3: пересчитано расчётов %s, изменились %s", len(specs), len(changed))
