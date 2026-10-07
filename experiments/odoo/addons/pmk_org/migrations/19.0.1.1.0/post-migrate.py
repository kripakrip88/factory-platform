# -*- coding: utf-8 -*-
"""Налоги режимов — «включён в цену» (разбор UX, шаг З-2, 08.10.2026).

На боевой базе: налог 7 «НДС 22% (продажа)» стоит у всех 753 товаров —
его не трогаем, только снимаем с него пометку режима; режиму «НДС 22%»
заводится свой налог «НДС 22% (в цене)». Налоги 8–10 (шаг 58, ни у одного
товара) включаются в цену на месте и переименовываются «… (в цене)».
Зачем — hooks.py, ensure_price_included. Повторный прогон ничего не меняет.

Должна пройти ДО первого счёта покупателю (pmk_orders): иначе первый счёт
выйдет на 22 % больше КП. pmk_orders зависит от pmk_org — при общей выкладке
обновление pmk_org идёт раньше.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_org.hooks import ensure_price_included

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.ref("base.main_company", raise_if_not_found=False) or env.company
    taxes = ensure_price_included(env, company)
    _logger.info("pmk_org 19.0.1.1.0: налоги режимов в цене — %s",
                 {regime: (tax.id, tax.name) for regime, tax in taxes.items()})
