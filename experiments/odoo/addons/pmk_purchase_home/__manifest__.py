# -*- coding: utf-8 -*-
{
    "name": "ПМК — Главная закупок",
    "summary": "«Закупки → Главная»: заявки на металл, поставки, свежесть прайсов, позиции без цены",
    "description": """
Антон 18.10.2026: «собери дашборд для главной страницы модуля закупки»; прототип показан,
смотрят оба — руководитель и снабженец; «В пути» оставить; прайсы — блоком «последний от
такого-то числа», маяк, что давно не обновляли.

Клиентское действие pmk_purchase_home, оформление — общее с главной продаж (pmk_sales_home,
классы o_pmk_home__*). Числа — от имени человека; нет прав на блок — нет блока.
""",
    "version": "19.0.1.0.0",
    "category": "Inventory/Purchase",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_sales_home", "pmk_theme", "pmk_purchase", "pmk_tech", "pmk_bridge", "pmk_orders"],
    "data": [
        "views/purchase_home.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_purchase_home/static/src/purchase_home.js",
            "pmk_purchase_home/static/src/purchase_home.xml",
            "pmk_purchase_home/static/src/purchase_home.scss",
        ],
    },
    "installable": True,
    "application": False,
}
