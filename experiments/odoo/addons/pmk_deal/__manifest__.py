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
    "version": "19.0.1.0.6",
    "summary": "Расчёт металлопроката привязан к сделке CRM",
    "category": "Sales/CRM",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # sale_crm — ради вида, который прячет штатные кнопки КП и ставит «Расчёт
    # и КП» (views/crm_lead_views.xml): xpath идёт по её узлу.
    # pmk_bridge — деньги расчёта (цена клиенту, металл, маржа, «без цены»)
    # живут в мосте; сделка показывает их строкой и берёт из них доход
    # (разбор UX, шаг 31). Мост уже стоит на боевой базе.
    # ⚠️ crm_sms НЕ в зависимостях, хоть шаг 31 и прячет кнопки «СМС»:
    # цепочка crm_sms → sms → iap_mail → iap, и удаление «SMS» или iap в
    # «Приложениях» каскадом снесло бы pmk_deal с полем «Сделка» у расчёта
    # (ловушка удаления модулей). Кнопки прячет мостик pmk_deal_sms
    # (auto_install): удалят SMS — уйдёт только он.
    "depends": ["crm", "sale_crm", "pmk_calc", "pmk_bridge"],
    "data": [
        "views/crm_lead_views.xml",
        "views/crm_lead_money_views.xml",
        "views/metal_spec_views.xml",
        # Кнопка-счётчик «Расчёты» в карточке клиента (разбор UX, шаг 28).
        "views/res_partner_views.xml",
        "data/crm_lost_reason.xml",
        "data/crm_pipeline_views.xml",
        # Маркетинговые метки (кампания, канал, источник) в поиске и списке
        # лидов — убраны (разбор UX, шаг 29, 02.10.2026).
        "views/step29_crm_hide.xml",
    ],
    # Стадия в списке сделок плашкой в цвете стадии («оживить таблицы»,
    # 29.09.2026) — свой виджет поверх штатного редактора стадии. Шаг 31 —
    # строка денег расчёта на сделке и на карточке воронки.
    # Приёмка 01.10.2026 (R10): шапка колонки воронки — полоса цвета этапа,
    # сумма «9,5 млн ₽», без полоски задач; колонки раздельно.
    "assets": {
        "web.assets_backend": [
            "pmk_deal/static/src/js/stage_badge_field.js",
            "pmk_deal/static/src/xml/stage_badge_field.xml",
            "pmk_deal/static/src/scss/deal_money.scss",
            "pmk_deal/static/src/js/money_short.js",
            "pmk_deal/static/src/js/pipeline_kanban.js",
            "pmk_deal/static/src/xml/pipeline_kanban.xml",
            "pmk_deal/static/src/scss/pipeline_kanban.scss",
        ],
    },
    # Сроки стадий и архив штатных причин проигрыша на новой базе — так же,
    # как миграция 19.0.1.0.4 делает на боевой.
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
