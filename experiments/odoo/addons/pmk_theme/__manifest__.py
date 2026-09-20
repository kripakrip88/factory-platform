# -*- coding: utf-8 -*-
{
    "name": "ПМК Парк — оформление",
    "summary": "Модули строкой в верхней панели вместо выпадающего меню",
    "description": """
Наша тема оформления Odoo. Первая задача — навигация: в штатной Odoo список
приложений спрятан в выпадающее меню, и до нужного модуля два клика. Делаем как
в нашем ERPNext (saas_theme): модули видны строкой в верхней панели.

Полный список приложений при этом НЕ пропадает — штатная кнопка остаётся
и работает как «все приложения». Так ничего не становится недостижимым,
когда модулей больше, чем влезает по ширине.
    """,
    "version": "19.0.1.0.0",
    "category": "Theme/Backend",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # Зависимости — все модули, на действия которых ссылается наше меню.
    # Без них Odoo не найдёт action при установке и упадёт.
    "depends": [
        "web", "crm", "sale_management", "purchase", "stock",
        "mrp", "account", "repair", "maintenance", "hr",
        "mail", "calendar", "project", "contacts", "project_todo", "spreadsheet_dashboard",
    ],
    "data": ["data/menus.xml", "data/hide_menus.xml"],
    "assets": {
        "web.assets_backend": [
            "pmk_theme/static/src/scss/navbar.scss",
            "pmk_theme/static/src/scss/forms.scss",
            "pmk_theme/static/src/js/collapsible_sections.js",
            "pmk_theme/static/src/scss/third_party.scss",
            # Индикаторы состояния (бейджи, полосы загрузки) и токены
            # состояния (--pmk-ok-*/--pmk-warn-*/--pmk-danger-*).
            #
            # Место в списке значения не имеет, и это проверено, а не
            # предположено: селекторы indicators.scss (.pmk-badge*, .pmk-meter*,
            # :root и вложенные .fa/svg) не встречаются больше ни в одном нашем
            # scss — драться за одинаковый вес не с кем. А токенами forms.scss
            # пользуется из строки ВЫШЕ по списку и прекрасно их находит: var()
            # резолвится в браузере, а не при сборке бандла.
            #
            # Если однажды тот же класс появится в двух наших файлах — вот
            # тогда порядок начнёт решать: при равном весе выигрывает тот, что
            # НИЖЕ в собранном файле, а собирается он ровно в порядке списка.
            "pmk_theme/static/src/scss/indicators.scss",
            "pmk_theme/static/src/js/navbar_active_section.js",
            "pmk_theme/static/src/js/chatter_inline.js",
            "pmk_theme/static/src/xml/navbar.xml",
            "pmk_theme/static/src/xml/chatter.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
