# -*- coding: utf-8 -*-
{
    # Калькулятор фундаментных болтов по ГОСТ 24379.1-2012 (Антон 21.10.2026):
    # отдельный документ в «Калькуляторах», как зонты; потом — «Добавить болты»
    # в счёт и расчёт. Состав — только материалы: круг и лист плиты — из общих
    # справочников по прайсам, гайки и шайбы — покупные (цену вписывают); наценка —
    # «Ценовая политика» по сезонам.
    "name": "ПМК: фундаментные болты",
    "version": "19.0.1.1.0",  # 19.0.1.1.0 — болты в расчёте и счёте
    "summary": "Калькулятор фундаментных болтов по ГОСТ 24379.1-2012, нормы, ценовая политика",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_calc", "pmk_bridge", "pmk_butik", "pmk_orders", "sale", "crm"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/policy.xml",
        "views/bolt_views.xml",
        "views/policy_views.xml",
        "views/spec_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_bolt/static/src/js/bolt_grid.js",
            "pmk_bolt/static/src/xml/bolt_grid.xml",
            "pmk_bolt/static/src/scss/bolt_grid.scss",
            "pmk_bolt/static/src/js/spec_bolt.js",
            "pmk_bolt/static/src/xml/spec_bolt.xml",
        ],
    },
    "installable": True,
}
