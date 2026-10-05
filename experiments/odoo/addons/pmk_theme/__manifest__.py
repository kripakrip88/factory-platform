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
    "version": "19.0.2.7.0",
    "category": "Theme/Backend",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # Зависимости — все модули, на действия которых ссылается наше меню.
    # Без них Odoo не найдёт action при установке и упадёт.
    # pmk_calc — ради «Продажи → Расчёты и КП» (разбор UX, шаг 38): пункт
    # открывает действие расчётов. pmk_calc зависит только от base, web,
    # mail и на pmk_theme не ссылается — цикла нет.
    "depends": [
        "web", "crm", "sale_management", "purchase", "stock",
        "mrp", "account", "repair", "maintenance", "hr",
        "mail", "calendar", "project", "contacts", "project_todo", "spreadsheet_dashboard",
        "pmk_calc",
    ],
    "data": [
        # Группа-выключатель «Опасные действия (показать)» — первой: на неё
        # ссылаются data/dangerous_actions.xml и views/res_config_settings_views.xml
        # (разбор UX, шаг 23, 01.10.2026).
        "security/pmk_theme_groups.xml",
        # Группы-выключатели шага 29 (02.10.2026): «Убранное», «Склад»,
        # «Деньги» (показать). На них ссылаются виды этого модуля и
        # pmk_partner / pmk_purchase — поэтому тоже в начале.
        "security/pmk_step29_groups.xml",
        # Группа-выключатель «Производство (показать)» (шаг 38, 05.10.2026):
        # на неё ссылается корень «Производства» в data/menus.xml.
        "security/pmk_step38_groups.xml",
        "data/menus.xml",
        "data/hide_menus.xml",
        # Наши стили в конец бандла. ВАЖНО: файл несёт сам подключение scss —
        # без него тема останется без стилей вовсе.
        "data/assets_order.xml",
        # Лента без «Отправить сообщение» и подписчиков, телефон без «SMS»
        # (шаг 29): hidden.scss, sequence 43 — после dark.scss.
        "data/assets_hidden.xml",
        # Язык страницы и запрет автоперевода: браузер принимал русский за
        # другой язык и переводил интерфейс («Сохранить» -> «чувак»).
        "views/webclient_lang.xml",
        # Опасное — только группе-выключателю, в ней никого нет (шаг 23):
        # портал, «Поделиться», начисленные расходы и выручка в шестерёнке;
        # галочки платных модулей IAP в Настройках.
        "data/dangerous_actions.xml",
        "views/res_config_settings_views.xml",
        # Пустые приёмки, отгрузки и перемещения — наследник шаблона
        # stock.help_message_template (разбор UX, шаг 26): ядро рисует его и
        # в меню, и в карточках «Обзора операций», поверх подсказки действия.
        "views/stock_empty_help.xml",
        # Убрать совсем и спрятать до востребования (шаг 29): «Мои
        # предпочтения» без календаря (оба окна: штатное и hr), «Сводка»
        # Odoo выключается один раз.
        # Узлы чужих модулей и шестерёнка — в models/ (hidden_nodes.py,
        # ir_actions.py): без зависимостей от website / project / maintenance.
        "views/step29_user_prefs.xml",
        "data/digest_off.xml",
        # Тема у человека (разбор UX, шаг 40): сервер ставит тёмный класс на
        # body до первой отрисовки — без белой вспышки при загрузке.
        # Поле и session_info — models/color_scheme.py.
        "views/webclient_color_scheme.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # SCSS здесь НЕТ намеренно — он подключается в data/assets_order.xml
            # записями append, чтобы попасть в САМЫЙ КОНЕЦ бандла и не проигрывать
            # чужой теме (она грузится после нас: модули сортируются по имени).
            # Добавляешь новый scss — добавляй туда же, иначе он окажется в
            # середине бандла. Порядок файлов и его обоснование — в шапке
            # data/assets_order.xml.
            # Копия чужой темы: её боковая панель приложений и переключатель.
            # Идут ПЕРВЫМИ, чтобы наш navbar_active_section.js правил уже
            # готовую разметку. Подробности — в data/assets_order.xml.
            # ── ГИБРИД С ЧУЖОЙ ТЕМОЙ (22.09.2026) ──────────────────────
            # Включены ровно два файла: разметка строки модулей и скрипт,
            # который помечает текущий раздел. Вместе со светлым
            # navbar_nexus.scss они дают нашу горизонтальную навигацию поверх
            # чужой светлой темы.
            #
            # Остальное намеренно выключено:
            #   • vendor/* — боковая панель из купленной темы, её место сейчас
            #     занимает панель чужой темы, две сразу не нужны;
            #   • collapsible_sections.js — сворачиваемые секции ФОРМЫ, к
            #     навигации отношения не имеет, тянет за собой стили форм;
            #   • chatter_* — переписка, её оформление идёт из чужой темы.
            #
            # Вернуть нашу тему целиком: включить 17 записей ir.asset
            # (active=true), выключить asset_scss_navbar_light, раскомментировать
            # строки ниже.
            # "pmk_theme/static/src/js/vendor/navbar_sidebar.js",
            # "pmk_theme/static/src/xml/vendor/apps_sidebar.xml",
            # "pmk_theme/static/src/js/collapsible_sections.js",
            # Ключи «где я» — чистые функции, прогоняются в node (шаг 23).
            # Раньше navbar_active_section.js, который их импортирует.
            "pmk_theme/static/src/js/active_section_keys.js",
            "pmk_theme/static/src/js/navbar_active_section.js",
            # Пять рабочих разделов строкой, остальные — в «Ещё»
            # (разбор UX, шаг 5, 28.09.2026).
            "pmk_theme/static/src/js/navbar_more.js",
            "pmk_theme/static/src/js/chatter_inline.js",
            # Правый верхний угол без переключателя компаний и лишних
            # пунктов меню аватара (разбор UX, 28.09.2026).
            "pmk_theme/static/src/js/systray_trim.js",
            # Строка пути: номера не обрезаются, подсказки по-русски
            # (разбор UX, шаг 2, 28.09.2026).
            "pmk_theme/static/src/xml/breadcrumbs.xml",
            # Кнопки-счётчики: подсказка вместо надписи, ноль серым
            # (разбор UX, шаг 3, 28.09.2026).
            "pmk_theme/static/src/js/stat_buttons.js",
            # Полоса стадий одной кнопкой со списком вместо ряда стрелок
            # (разбор UX, шаг 4, 28.09.2026).
            "pmk_theme/static/src/js/statusbar_compact.js",
            # Нули в таблицах бледные («оживить таблицы», 29.09.2026).
            "pmk_theme/static/src/js/list_zero.js",
            # Деньги в списках без копеек (Антон, 29.09.2026).
            "pmk_theme/static/src/js/list_money.js",
            # Таблицы одного вида (разбор UX, шаг 24, 01.10.2026): без пустых
            # строк-распорок, знаки итога как в строках. Правила — чистые
            # функции (их гоняет node), идут раньше патча, который их
            # импортирует. После list_money.js: патч getActiveColumns
            # оборачивает его и видит уже расставленные знаки денег.
            "pmk_theme/static/src/js/list_table_rules.js",
            "pmk_theme/static/src/js/list_table.js",
            "pmk_theme/static/src/xml/statusbar_compact.xml",
            "pmk_theme/static/src/xml/navbar.xml",
            "pmk_theme/static/src/xml/chatter.xml",
            # Пустые экраны без «помощников» (разбор UX, шаг 26, 01.10.2026):
            # видео в КП и BillGuide у счетов поставщиков. Текст подсказки и
            # отключение демо-строк — models/, стиль — forms_nexus.scss,
            # раздел 7.
            "pmk_theme/static/src/xml/empty_screens.xml",
            # Тема у человека (разбор UX, шаг 40, 05.10.2026): переключатель
            # пишет выбор в res.users, до первой отрисовки шапки состояние
            # берётся с сервера. Правила — чистые функции (их гоняет node),
            # идут раньше патча, который их импортирует.
            "pmk_theme/static/src/js/color_scheme_rules.js",
            "pmk_theme/static/src/js/color_scheme.js",
        ],
        # ⚠️ ОТЛОЖЕННЫЙ БАНДЛ, И ЭТО НЕ ВКУСОВЩИНА.
        # canvas_text.js красит подписи осей и легенду графика: до них CSS не
        # достаёт, цвет задаёт JS (ядро выбирает его ОДИН РАЗ при загрузке
        # модуля и в светлой схеме берёт почти чёрный — на нашей тёмной
        # карточке графика подписи пропадают).
        #
        # Патчить надо @web/views/graph/graph_renderer, а вид «График» лежит в
        # ОТЛОЖЕННОМ бандле: web/__manifest__.py сначала исключает
        # 'web/static/src/views/graph/**' из web.assets_backend и включает в
        # web.assets_backend_lazy. Положишь патч в обычный бандл — импорт там
        # не разрешится, патч молча не применится, и узнаешь об этом только
        # когда кто-нибудь откроет график. Чужая тема подключала свой такой же
        # файл ровно сюда же.
        "web.assets_backend_lazy": [
            "pmk_theme/static/src/js/canvas_text.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
