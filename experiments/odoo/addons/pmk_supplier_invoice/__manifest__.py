# -*- coding: utf-8 -*-
{
    # Счета поставщиков → цены (Антон 25.10.2026): входящие счета на оплату с
    # pmkpark@mail.ru читает ассистент в фоне, строки сопоставляются со справочником,
    # Голубенко проверяет и жмёт «Обновить цены» — цена поставщика с датой счёта.
    "name": "ПМК: счета поставщиков → цены",
    "version": "19.0.1.0.2",  # 19.0.1.0.2 — лист: цена и масса за лист, НДС из сумм
    "summary": "Распознавание счетов на оплату от поставщиков и обновление цен поставщиков",
    "category": "Purchases",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_ai", "pmk_ai_mail", "pmk_mail_ui", "pmk_bridge", "pmk_purchase", "pmk_theme", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/invoice_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_supplier_invoice/static/src/scss/invoice.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
}
