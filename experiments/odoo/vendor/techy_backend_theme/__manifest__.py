# -*- coding: utf-8 -*-
# Part of Techy Backend Theme.

{
    'name': 'Techy Backend Theme',
    'version': '19.0.1.0.0',
    'category': 'Theme/Backend',
    'summary': 'Elegant, fancy and professional backend theme for Odoo 19 (CSS only)',
    'description': """
Techy Backend Theme
===================
A modern, elegant and professional backend theme for Odoo 19, built with
pure CSS (no JavaScript, no SCSS compilation).

Highlights
----------
* Dark gradient top navbar with refined hover effects
* Indigo/violet accent palette with gradient primary buttons
* Card-style form sheets, list views and kanban records
* Soft layered shadows, rounded corners and smooth transitions
* Restyled statusbar, badges, breadcrumbs, chatter and dialogs
* Custom slim scrollbars
""",
    'author': 'Techfellows',
    'website': 'https://www.techfellows.net',
    'license': 'LGPL-3',
    'depends': ['web'],
    'category': 'Theme/Backend',
    'data': [],
    'assets': {
        'web.assets_backend': [
            'techy_backend_theme/static/src/css/**/*',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
