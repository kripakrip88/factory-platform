{
    # ПРОИСХОЖДЕНИЕ. Модуль вырос из codeerts_transaction_flow_visualizer
    # (CODEerts, LGPL-3, 19.0.1.0.2) — он лежал в vendor/ и показывал схему
    # связей штатных документов Odoo по кнопке «Flow Map».
    #
    # Решение владельца 27.09.2026: «то, что модуль обновляется, думаю, для
    # нас лишнее, я бы взял его код и дописал под нас так, как мы это хотим
    # видеть». Это тот же приём, что сработал с темой: копия целиком, потом
    # правка под себя. Обновлений от автора мы больше не ждём и не принимаем.
    #
    # Авторство исходного кода сохранено, лицензия прежняя — LGPL-3.
    'name': 'ПМК: схема связей документов',
    'version': '19.0.2.0.0',
    'category': 'Productivity',
    'summary': 'Как связаны заявка, расчёт, раскрой, заказ и производство — одной схемой',
    'description': 'Схема связанных документов завода: от лида и сделки через '
                   'расчёт металлопроката и раскрой до заказа, производства и '
                   'закупки. Ничего не хранит — строит по данным при открытии.',
    'author': 'ПМК Парк (на основе CODEerts Transaction Flow Visualizer)',
    'website': 'https://erppark.ru',
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
            'pmk_flow/static/src/flow_map.scss',
            'pmk_flow/static/src/flow_map.js',
            'pmk_flow/static/src/flow_map.xml',
        ],
    },
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': False,
}
