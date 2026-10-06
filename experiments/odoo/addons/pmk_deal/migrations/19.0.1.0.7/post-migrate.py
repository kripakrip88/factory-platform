# -*- coding: utf-8 -*-
"""Шаг 48 разбора UX (06.10.2026): номера «СД-» активным сделкам.

Колонки pmk_number и pmk_number_date и нумератор «Сделка» (СД-, 5 знаков)
создаёт обновление модуля; здесь номера получают сделки, которые уже есть.
Только активные, по дню превращения в сделку (hooks.py, number_active_deals).
Ожидаемо на боевой базе (06.10.2026): id 12 → СД-00001 от 27.09.2026,
id 19 → СД-00002 от 03.10.2026; архивные 1–4 и все лиды — без номера.
Повторный запуск ничего не меняет.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_deal.hooks import number_active_deals


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    number_active_deals(env)
