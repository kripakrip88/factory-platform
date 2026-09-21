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
    "version": "19.0.1.2.0",
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
    "data": [
        "data/menus.xml",
        "data/hide_menus.xml",
        # Наши стили в конец бандла. ВАЖНО: файл несёт сам подключение scss —
        # без него тема останется без стилей вовсе.
        "data/assets_order.xml",
        # Язык страницы и запрет автоперевода: браузер принимал русский за
        # другой язык и переводил интерфейс («Сохранить» -> «чувак»).
        "views/webclient_lang.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # SCSS здесь НЕТ намеренно — он подключается в data/assets_order.xml
            # записями append, чтобы попасть в САМЫЙ КОНЕЦ бандла и не проигрывать
            # чужой теме (она грузится после нас: модули сортируются по имени).
            # Добавляешь новый scss — добавляй туда же, иначе он окажется в
            # середине бандла. Причина и история — в шапке того файла.
            "pmk_theme/static/src/js/collapsible_sections.js",
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
