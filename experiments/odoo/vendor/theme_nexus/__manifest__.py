# -*- coding: utf-8 -*-
#############################################################################
#
#    NEXUS Backend Theme
#    A modern enterprise backend theme for Odoo 18 Community
#    Author: Hồng Ngọc Phú — Industrial Management Researcher, Can Tho University
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#############################################################################
{
    'name': 'NEXUS Backend Theme',
    # 18.0.1.0.0 → 19.0: переименование, а НЕ портирование. Odoo версию из
    # манифеста при установке не сверяет, но держать в дереве 19-й стенд модуль
    # с меткой 18 — прямой путь к путанице при следующем обновлении.
    #
    # Всё, чем тема цепляется за внутренности Odoo, проверено в ядре 19 перед
    # установкой (22.09.2026):
    #   • шаблон web.NavBar.AppsMenu сохранил структуру, на которую наложен
    #     xpath темы: <t t-else=""> → <div t-if="!isScopedApp"> (navbar.xml:81-82);
    #   • директива t-portal жива — ядро использует её само (navbar.xml:106);
    #   • menuService, getApps(), selectMenu(), getCurrentApp() на месте
    #     (navbar.js:42, 207, 89; menu_service.js:70).
    'version': '19.0.1.0.0',
    'category': 'Theme/Backend',
    'summary': 'A modern, intelligent and premium Odoo Enterprise backend experience',
    'description': """
NEXUS Backend Theme
====================
A clean enterprise-grade backend theme for Odoo 18 Community: a persistent
dark application sidebar with an orange accent, bright rounded content
cards, restyled buttons / lists / kanban / forms / modals, and Swiss-grid
inspired spacing and typography.

Features
--------
- Persistent left application sidebar (auto-pins on desktop, slides in as
  a drawer on smaller screens)
- Light / Dark content mode toggle
- Restyled buttons, form sheets, statusbar, notebook tabs
- Restyled list, kanban, and calendar views
- Restyled modals / dialogs
- Custom scrollbars, focus rings and selection color
- Fully responsive, RTL-safe (no hardcoded left/right physical properties
  outside the sidebar rail itself)
    """,
    'author': 'Hồng Ngọc Phú',
    'website': 'https://github.com/',
    'license': 'LGPL-3',
    'depends': ['web', 'base'],
    'assets': {
        # Переменные фирменной палитры Odoo — ОТДЕЛЬНЫМ бандлом и обязательно
        # prepend: они объявлены в ядре с !default, и файл, попавший в конец,
        # опоздал бы. Подробности и замеры — в самом primary_variables.scss.
        'web._assets_primary_variables': [
            ('prepend', 'theme_nexus/static/src/scss/primary_variables.scss'),
        ],
        'web.assets_backend': [
            'theme_nexus/static/src/scss/variables.scss',
            'theme_nexus/static/src/scss/buttons.scss',
            'theme_nexus/static/src/scss/forms.scss',
            'theme_nexus/static/src/scss/lists.scss',
            'theme_nexus/static/src/scss/kanban.scss',
            'theme_nexus/static/src/scss/modals.scss',
            'theme_nexus/static/src/scss/navbar.scss',
            # ── БОКОВАЯ ПАНЕЛЬ ВЫКЛЮЧЕНА (ПМК, 22.09.2026) ─────────────
            # При горизонтальном меню ПМК она дублирует строку модулей.
            #
            # ⚠️ ГАСИТЬ ТОЛЬКО ТРОЙКОЙ. JS без XML вешает на body класс
            # o_nexus_sidebar_pinned, и контент уезжает вправо на 240 px в
            # пустоту; XML без JS роняет Owl на неизвестных ему именах —
            # белый экран. Поэтому три строки ниже выключаются вместе.
            #
            # dark_mode.js и dark_mode.scss ОСТАВЛЕНЫ: в них механизм
            # переключения тем. Его кнопка жила в подвале этой панели, и
            # вместо неё теперь ползунок в шапке — pmk_theme/static/src/xml/
            # theme_toggle.xml.
            # 'theme_nexus/static/src/scss/sidebar.scss',
            'theme_nexus/static/src/scss/theme_nexus.scss',
            'theme_nexus/static/src/scss/dark_mode.scss',
            # 'theme_nexus/static/src/xml/navbar.xml',
            # 'theme_nexus/static/src/js/navbar.js',
            'theme_nexus/static/src/js/dark_mode.js',
        ],
    },
    'images': [
        'static/description/banner.jpg',
        'static/description/theme_screenshot.jpg',
        'static/description/icon.png',
    ],
    'installable': True,
    'application': False,
}
