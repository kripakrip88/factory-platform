# -*- coding: utf-8 -*-
{
    "name": "ПМК — Бутик: спецификация как в Excel",
    "summary": "Отдельный калькулятор «Бутик»: спецификация таблицей, как её пишет Бутов в Excel",
    "description": """
Антон 15.10.2026: «для Бутова можем пока что сделать как отдельный модуль? В основном
флоу ничего не менять, сделать в калькуляторах отдельную вкладку "Бутик" со списком
расчётов, при открытии — такая таблица и возможность привязать расчёт к сделке. В
строках — умный поиск по номенклатуре, как в основной системе».

Формат — как в файлах Бутова (разбор 9 спецификаций, 15.10): блок изделия (название с
шифром и покрытием, количество изделий), строки деталей: № поз., наименование одной
ячейкой («Уголок 63х4», «Лист 10х60» = толщина × ширина, длина — в своей колонке), длина,
количество на 1 шт, всего, марка; вес считается сам. Клавиатура как в Excel: стрелки,
Enter, Tab, Ctrl+D, вставка блока из Excel.

Наименование ищется умным поиском справочников pmk_calc (name_search проката и листа —
size_search.py), метизы — по справочнику метизов. Основной расчёт металлопроката, сделки
и вкладки не меняются: модуль только добавляет пункт меню.
""",
    "version": "19.0.1.2.0",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_calc", "pmk_bridge", "crm", "pmk_flow"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "views/butik_views.xml",
        # 20.10.2026: «Конструкции» — эта же таблица во вкладке состава расчёта.
        "views/konstr_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_butik/static/src/js/butik_grid.js",
            "pmk_butik/static/src/xml/butik_grid.xml",
            "pmk_butik/static/src/scss/butik_grid.scss",
            "pmk_butik/static/src/js/konstr_grid.js",
            "pmk_butik/static/src/xml/konstr_grid.xml",
            "pmk_butik/static/src/scss/konstr_grid.scss",
        ],
    },
    "installable": True,
    "application": False,
}
