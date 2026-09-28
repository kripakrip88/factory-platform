# -*- coding: utf-8 -*-
{
    # Связь сделки с расчётом металлопроката.
    #
    # ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Калькулятор (pmk_calc) намеренно не зависит ни от
    # склада, ни от продаж: он должен считать вес и до того, как в системе
    # появятся сделки. Мост в номенклатуру (pmk_bridge) отвечает за товары и
    # цены, CRM его не касается. Поэтому связка «сделка ↔ расчёт» живёт своим
    # модулем: не установлен — обе стороны работают как раньше.
    "name": "ПМК: сделка и расчёт",
    "version": "19.0.1.0.3",
    "summary": "Расчёт металлопроката привязан к сделке CRM",
    "category": "Sales/CRM",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # sale_crm — ради вида, который прячет пустую кнопку штатных КП
    # (views/crm_lead_views.xml): xpath идёт по её узлу.
    "depends": ["crm", "sale_crm", "pmk_calc"],
    "data": [
        "views/crm_lead_views.xml",
        "views/metal_spec_views.xml",
    ],
    # Стадия в списке сделок плашкой в цвете стадии («оживить таблицы»,
    # 29.09.2026) — свой виджет поверх штатного редактора стадии.
    "assets": {
        "web.assets_backend": [
            "pmk_deal/static/src/js/stage_badge_field.js",
            "pmk_deal/static/src/xml/stage_badge_field.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
