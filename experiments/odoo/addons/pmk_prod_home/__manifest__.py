# -*- coding: utf-8 -*-
{
    "name": "ПМК — Главная производства",
    "summary": "«Производство → Главная» для инженера; лазер, калькуляторы и заказы в работе — в «Производстве»",
    "description": """
Антон 16.10.2026: «сделай прототип главной инженера, она пойдёт в модуль производства.
Лазерную резку, заказы в работе и калькуляторы все перенесём в модуль производства».
Прототип принят («прототип нравится, делай»). «Лазерная резка» и «Калькуляторы» уходят
из верхнего меню внутрь «Производства»; «Заказы в работе» остаются и в «Продажах».

Главная — клиентское действие pmk_prod_home (оформление — общее с главной продаж,
pmk_sales_home). Числа — от имени человека; лазер, металл, техрасчёт — мягко.
""",
    "version": "19.0.1.0.0",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_sales_home", "pmk_theme", "pmk_calc", "pmk_laser", "pmk_orders", "pmk_cut", "pmk_tech"],
    "data": [
        "views/prod_home.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_prod_home/static/src/prod_home.js",
            "pmk_prod_home/static/src/prod_home.xml",
            "pmk_prod_home/static/src/prod_home.scss",
        ],
    },
    "installable": True,
    "application": False,
}
