# -*- coding: utf-8 -*-
"""Цвет печати и писем — чёрный (разбор UX, шаг 30, 02.10.2026).

Что и почему — pmk_bridge/tools/print_colors.py; как вернуть —
docs/disabled-features.md, шаг 30.

ПОЧЕМУ МИГРАЦИЯ, А НЕ ЗАПИСЬ В XML. Компания — запись base.main_company с
noupdate в ir_model_data: при -u Odoo такие записи пропускает
(_load_records), правка XML до живой базы не доехала бы. И нужен именно
write через ORM — он пересобирает стили отчётов компании.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_bridge.tools.print_colors import make_black

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company_id, old in make_black(env).items():
        _logger.info("Шаг 30: компания %s — цвета печати и писем чёрные, было %s",
                     company_id, old)
