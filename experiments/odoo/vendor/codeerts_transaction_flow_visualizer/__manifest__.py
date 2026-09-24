{
    'name': 'Transaction Flow Visualizer | Odoo Document Flow & Relationship Map | Linked Records Diagram | Sales-Purchase-MRP Flow Chart',
    'version': '19.0.1.0.2',
    'category': 'Productivity',
    'summary': 'Interactive visual map of linked Odoo documents across Sales, Purchase, Manufacturing, Inventory and Accounting, tracing a whole transaction chain from one screen.',
    'description': 'On-demand flow chart of related transactions behind a Flow Map '
                   'smart button. No data is stored.',
    'author': 'CODEerts',
    'website': 'https://www.codeerts.com',
    'support': 'support@codeerts.com',
    'license': 'LGPL-3',
    'depends': [
        'sale_management', 'purchase', 'stock', 'account', 'mrp',
        'sale_stock', 'sale_purchase', 'purchase_stock', 'sale_mrp', 'purchase_mrp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/flow_buttons.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'codeerts_transaction_flow_visualizer/static/src/flow_map.scss',
            'codeerts_transaction_flow_visualizer/static/src/flow_map.js',
            'codeerts_transaction_flow_visualizer/static/src/flow_map.xml',
        ],
    },
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': False,
}
