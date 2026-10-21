# -*- coding: utf-8 -*-
{
    # Калькулятор фундаментных болтов по ГОСТ 24379.1-2012 (Антон 21.10.2026):
    # отдельный документ в «Калькуляторах», как зонты; потом — «Добавить болты»
    # в счёт и расчёт. Справочники: нормы работ и металла по диаметрам (правит
    # Владимир, с датой проверки) и ценовая политика — наценка по сезонам.
    "name": "ПМК: фундаментные болты",
    "version": "19.0.1.0.0",
    "summary": "Калькулятор фундаментных болтов по ГОСТ 24379.1-2012, нормы, ценовая политика",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_calc", "pmk_butik", "sale", "crm"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/norms.xml",
        "views/bolt_views.xml",
        "views/norm_views.xml",
        "views/policy_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_bolt/static/src/js/bolt_grid.js",
            "pmk_bolt/static/src/xml/bolt_grid.xml",
            "pmk_bolt/static/src/scss/bolt_grid.scss",
        ],
    },
    "installable": True,
}
