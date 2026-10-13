# -*- coding: utf-8 -*-
"""Короткие названия у уже заведённых контрагентов (Антон 14.10.2026):
«ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "…"» → «ООО «…»», «ИП Фамилия Имя
Отчество» → «ИП Фамилия И.О.». Длинное — в «Полное наименование», если там
пусто (это делает write карточки). Архивные — тоже."""

import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_dadata.tools.legal_name import short_name

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    partners = env["res.partner"].search([])
    changed = 0
    for partner in partners:
        if partner.name and short_name(partner.name) != partner.name:
            partner.write({"name": partner.name})
            changed += 1
    _logger.info("pmk_dadata: короткие названия — %s карточек", changed)
