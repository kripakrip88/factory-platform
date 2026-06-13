"""
Rail Icons — логика встроена напрямую в saas_theme.js (v77+).

Причина: Frappe v16 не поддерживает Global Client Script (dt — обязательное поле).
Поэтому скрытие Search/Notifications из сайдбара и инжект иконок в рейл
реализованы в saas_theme.sidebar.hide_sidebar_duplicates() и
saas_theme.sidebar.inject_rail_bottom_icons() внутри saas_theme.js.

Этот файл — заглушка для совместимости с setup_all.py.
"""

import frappe


def execute():
    print("Rail icons: logic is embedded in saas_theme.js v77+ — no Client Script needed")
