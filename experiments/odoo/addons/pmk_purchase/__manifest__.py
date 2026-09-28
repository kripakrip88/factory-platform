{
    "name": "ПМК — поставщики и прайсы",
    "version": "19.0.1.0.2",
    "summary": "Реестр поставщиков прайсов: что возит, куда писать, как часто, когда был последний прайс",
    "description": """
В Odoo нет понятия «поставщик, у которого мы запрашиваем прайс». Штатный
признак `supplier_rank` растёт только когда проведён счёт поставщика, то есть
тот, кому мы ещё ничего не оплатили, в список поставщиков не попадает вовсе.
Нет и полей: что поставщик возит, на какой адрес просить прайс, как часто,
когда прайс приходил в последний раз.

Этот модуль добавляет ровно эту недостающую часть и ничего не дублирует:
условия оплаты, валюта закупки, закупщик, своевременность поставок и цены
(`product.supplierinfo`) остаются штатными.

**Адрес для запроса живёт в отдельном поле, а не в `email`.** Так сделано
намеренно: список собран из открытых источников, часть адресов ещё не
подтверждена, а пустой `email` означает, что ни одна штатная рассылка Odoo
физически не сможет написать этому контрагенту. Адрес переезжает в `email`
только после подтверждения — руками или проверкой.
""",
    "category": "Purchases",
    "author": "ПМК Парк",
    "depends": ["purchase", "pmk_theme"],
    "data": [
        "security/ir.model.access.csv",
        "data/supply_category.xml",
        "data/mail_template.xml",
        "data/ir_cron.xml",
        "views/supply_category_views.xml",
        "views/res_partner_views.xml",
        "views/price_mailing_views.xml",
        "views/menus.xml",
        # «Запрос КП» в заголовке формы закупки (разбор UX, 28.09.2026).
        "views/purchase_order_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
    # Панель над «Запросами КП» — подписи и подсказки по-русски (29.09.2026).
    "assets": {
        "web.assets_backend": [
            "pmk_purchase/static/src/scss/purchase_dashboard.scss",
            "pmk_purchase/static/src/xml/purchase_dashboard.xml",
        ],
    },
    "installable": True,
    "application": False,
}
