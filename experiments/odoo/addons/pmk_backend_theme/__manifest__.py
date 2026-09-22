# -*- coding: utf-8 -*-
{
    'name': 'ПМК Парк — тема бэкенда',
    'version': '19.0.1.0.0',
    'category': 'Theme/Backend',
    'summary': 'Собственная тёмная тема Odoo для ПМК Парк — без зависимости от сторонних тем',
    'description': """
Плоский тёмный интерфейс на фирменных цветах ПМК Парк (design-system.css с
pmkpark.ru): акцент лайм #C8F000 на тёмном ink #16191C, шрифт Manrope.

Без глассморфизма/блюра: для плотных рабочих экранов важнее контраст и
читаемость, чем эффект стекла. Переопределяет штатные классы веб-клиента
Odoo 19 напрямую — не зависит от theme_liquid_glass и не патчит её.

Не покрыто (см. README.md): светлая тема, боковой ящик приложений
(o_apps_sidebar) — дублирует горизонтальную навигацию pmk_theme, цвета
vendor/mail_client и калькуляторов pmk_calc — отдельные модули со своей
темизацией.
    """,
    'author': 'ПМК Парк',
    'website': 'https://pmkpark.ru',
    'license': 'LGPL-3',
    'depends': ['web', 'base'],
    'assets': {
        'web.assets_backend': [
            'pmk_backend_theme/static/src/scss/variables.scss',
            'pmk_backend_theme/static/src/scss/base.scss',
            'pmk_backend_theme/static/src/scss/navbar.scss',
            'pmk_backend_theme/static/src/scss/buttons.scss',
            'pmk_backend_theme/static/src/scss/forms.scss',
            'pmk_backend_theme/static/src/scss/lists.scss',
            'pmk_backend_theme/static/src/scss/kanban.scss',
            'pmk_backend_theme/static/src/scss/modals.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
