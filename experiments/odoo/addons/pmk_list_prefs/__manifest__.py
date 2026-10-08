# -*- coding: utf-8 -*-
{
    # Колонки у каждого (разбор UX, шаг 55, 08.10.2026).
    #
    # Антон, 07.10: «Попробовал изменить размеры колонок в таблице, но после
    # перезагрузки всё вернулось обратно… Чтобы каждый мог донастроить
    # систему для себя»; к шагу 24 — менять колонки местами и включать /
    # отключать в том числе наши дописанные колонки. Решение 07.10: ОБА
    # варианта — каждый настраивает себе, администратор может сделать
    # «так у всех по умолчанию». 08.10: переставлять колонки — да.
    #
    # Отдельный маленький модуль, как предлагал «Разбор удобства»: снимается
    # одной кнопкой, все настройки — в его таблице pmk_list_prefs. Без него
    # списки ровно как у ядра.
    "name": "ПМК: колонки списков у каждого",
    "version": "19.0.1.0.0",
    "summary": "Ширины, порядок и видимость колонок списков — у каждого человека, на сервере",
    "category": "Hidden/Tools",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # web — список, меню ⚙ и окно ядра, которые патчим;
    # pmk_theme — порядок в бандле: наш патч getActiveColumns ложится поверх
    #   list_money.js / list_table.js шага 24 и видит уже расставленные знаки;
    #   стили окна «Колонки» и перетаскивания — в живых файлах темы
    #   (forms_nexus.scss / dark.scss, раздел «Шаг 55»).
    "depends": ["web", "pmk_theme"],
    "data": [
        "security/ir.model.access.csv",
        "security/list_prefs_rules.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # Правила — чистые функции (их гоняет node,
            # static/tests/list_prefs_step55.test.mjs), идут раньше файлов,
            # которые их импортируют.
            "pmk_list_prefs/static/src/js/list_prefs_rules.js",
            "pmk_list_prefs/static/src/js/list_prefs_store.js",
            "pmk_list_prefs/static/src/js/columns_dialog.js",
            "pmk_list_prefs/static/src/xml/columns_dialog.xml",
            "pmk_list_prefs/static/src/js/list_prefs.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
