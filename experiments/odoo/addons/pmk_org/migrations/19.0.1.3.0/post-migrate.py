# -*- coding: utf-8 -*-
"""Режим «НДС 20%» (12.10.2026): налог «НДС 20% (продажа)» в группе «НДС 20%».

Нужен истории ИП Чулкова — счета МоегоСклада до 2026 года (НДС 20%, в цене).
ensure_taxes заводит недостающие налоги режимов копией «НДС 22%» (та же страна,
счета и «Включён в цену»), уже заведённые не трогает. Повторный прогон ничего не
меняет.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_org.hooks import ensure_tax_groups, ensure_taxes

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.ref("base.main_company", raise_if_not_found=False) or env.company
    taxes = ensure_taxes(env, company)
    ensure_tax_groups(env, company)
    _logger.info("pmk_org 19.0.1.3.0: налог режима «НДС 20%%» — %s", taxes["vat20"].display_name)
