{
    'name': 'Team Inbox | Shared Email Inbox, Shared Mailbox, Unified Inbox, Team Email Management',
    'version': '19.0.1.0.0',
    'summary': 'Team inbox odoo, shared email inbox, shared mailbox, unified mailbox, unified inbox, team email, mail inbox odoo, incoming email, outgoing email, group mailbox, common inbox, email management',
    'category': 'Discuss',
    'author': 'Northlight',
    'website': 'https://alaskahub.io',
    'support': 'alisa@alaskahub.io',
    'depends': ['mail'],
    'auto_install': False,
    'images': ['static/description/banner.gif'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/teaminbox_basic_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'northlight_teaminbox/static/src/css/teaminbox_basic.css',
            'northlight_teaminbox/static/src/xml/teaminbox_basic.xml',
            'northlight_teaminbox/static/src/js/teaminbox_basic.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
