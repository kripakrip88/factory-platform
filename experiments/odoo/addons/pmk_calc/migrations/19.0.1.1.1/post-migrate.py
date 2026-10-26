# -*- coding: utf-8 -*-
"""Гайки ГОСТ 5915, заведённые калькулятором болтов до 26.10.2026 («Гайка М20 ГОСТ 5915», без
цены и карточки), — в архив, если в справочнике есть настоящая позиция с ценой (fast2_nut_*_black):
в каталоге и подборе не двоятся. Строки расчётов на них остаются как были (Антон 26.10:
старые расчёты не пересчитывать)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Fastener = env["pmk.metal.fastener"]
    ext = Fastener.search([]).get_external_id()
    for nut in Fastener.search([("fastener_type", "=", "nut"), ("gost", "=like", "ГОСТ 5915%"),
                                ("pmk_pending", "=", False)]):
        if ext.get(nut.id) or nut.strength_class:
            continue
        twin = Fastener._pmk_resolve("Гайка %s" % nut.size_label)
        if twin and twin != nut:
            nut.active = False
