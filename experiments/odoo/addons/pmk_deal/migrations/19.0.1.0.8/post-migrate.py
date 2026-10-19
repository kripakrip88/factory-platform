# -*- coding: utf-8 -*-
"""19.0.1.0.8 — стадии «сделка → (расчёт) → счёт» (Антон 20.10.2026).

Заявка → Расчёт → Счёт выставлен → Оплачено / в работе → Закрыта (выигрышная).
«КП отправлено» убрана: её сделки — в «Расчёт» (на боевом 20.10 — ни одной).
Логика — hooks.apply_funnel_stages (та же при установке).
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_deal.hooks import apply_funnel_stages

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    moved = apply_funnel_stages(env)
    _logger.info("pmk_deal 19.0.1.0.8: воронка перестроена, из «КП отправлено» в «Расчёт»: %s", moved)
