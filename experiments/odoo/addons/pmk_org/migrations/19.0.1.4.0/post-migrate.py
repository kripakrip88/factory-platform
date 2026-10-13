# -*- coding: utf-8 -*-
"""Короткие названия «Наших организаций» (Антон 14.10.2026): «ИП Чулков
Владислав Витальевич» → «ИП Чулков В.В.». Полное — в «Полное наименование»
карточки, из него печать КП берёт полное ФИО (pmk.org._pmk_print_name).
Отдельно от миграции pmk_dadata: тот модуль обновляется раньше, и зеркало
названия у организации там не пересчитывается."""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    for org in env["pmk.org"].search([]):
        before = org.name
        org.write({"name": before})
        if org.name != before:
            _logger.info("pmk_org: «%s» → «%s»", before, org.name)
