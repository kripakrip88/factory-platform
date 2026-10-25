# -*- coding: utf-8 -*-
{
    "name": "ПМК — ИИ-ассистент (Claude)",
    "summary": "Ассистент менеджера и инженера на Claude: панель ✦ справа, только чтение, расход и лимит видны всем",
    "description": """
Антон 16–17.10.2026: ассистент для менеджера и инженера на Anthropic API (прототип панели
показан 17.10). Шаг 1 — «Настройки → Ассистент»: ключ (вписывает Антон, в чат не шлёт),
адрес API и модель, «Проверить связь».

Связь с API с нашего VPS медленная и неровная (замер 17.10: рукопожатие TLS 4–10 с,
иногда запрос висит 60–130 с) — клиент держит соединение открытым (keep-alive),
с запасом по времени и одним повтором. Адрес API — настройка: при нужде запросы
пойдут через ретранслятор, без правки кода (как pmk_telegram.api_base).
""",
    "version": "19.0.0.3.0",
    "category": "Productivity",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["base_setup", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_ai/static/src/ai_panel.js",
            "pmk_ai/static/src/ai_panel.xml",
            "pmk_ai/static/src/ai_panel.scss",
        ],
    },
    "installable": True,
    "application": False,
}
