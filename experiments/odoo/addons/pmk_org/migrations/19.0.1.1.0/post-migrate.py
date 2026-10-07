# -*- coding: utf-8 -*-
"""Компания — «цены включают налог» (разбор UX, шаг З-2, 08.10.2026).

Решение Антона: цены ВСЕГДА с НДС, в счетах налог в цене. На боевой базе
компания «ИП Чулков» переводится в режим account_price_include =
tax_included; налоги с пустым «Включён в цену» (7 «НДС 22% (продажа)», 8–10
режимов, 6 «НДС 22% (покупка)») следуют компании. Имена, группы и пометки
налогов не меняются, новых налогов нет. Зачем и что это значит — hooks.py,
ensure_company_price_included. Повторный прогон ничего не меняет.

Должна пройти ДО первого счёта покупателю (pmk_orders): иначе первый счёт
выйдет на 22 % больше КП. pmk_orders зависит от pmk_org — при общей выкладке
обновление pmk_org идёт раньше.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_org.hooks import ensure_company_price_included

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.ref("base.main_company", raise_if_not_found=False) or env.company
    done = ensure_company_price_included(env, company)
    _logger.info("pmk_org 19.0.1.1.0: компания %s — цены включают налог: %s",
                 company.name, "да" if done else "НЕТ (см. ошибку выше)")
