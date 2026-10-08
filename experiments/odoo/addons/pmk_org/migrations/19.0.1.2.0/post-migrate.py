# -*- coding: utf-8 -*-
"""Шаг З-9: налог режима — в группе со словом режима.

На боевой налог 7 «НДС 22% (продажа)» стоит в группе плана счетов «Налог
15%» — в итогах счёта покупателю было «Налог 15%» при ставке 22%. Переводим
его в группу «НДС 22%» (заводится); группу «Налог 15%» не переименовываем —
её делят налоги 1, 2 (15%) и закупочный 6. Ставки, «Включён в цену», счета и
пометки режимов не меняются. Подробно — hooks.ensure_tax_groups. Повторный
прогон ничего не меняет.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_org.hooks import ensure_tax_groups

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.ref("base.main_company", raise_if_not_found=False) or env.company
    moved = ensure_tax_groups(env, company)
    _logger.info("pmk_org 19.0.1.2.0: групп налогов переведено — %s (%s)",
                 len(moved), ", ".join(sorted(moved)) or "ничего")
