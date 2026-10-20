# -*- coding: utf-8 -*-
{
    "name": "ПМК — разбор почты ассистентом",
    "summary": "Ассистент читает «Входящие» pmkpark@mail.ru: заявки — сделками в колонку «Разобрал ассистент»",
    "description": """
Антон 20.10.2026: «подключить ассистента для разбора почты». Новые письма «Входящих»
ящика заявок читает ассистент (Claude) в фоне: вид письма, а для заявки — клиент,
что нужно, сроки, место, чего не хватает; вложения PDF, сканы, Excel, Word.
Заявка — сделка в колонке «Разобрал ассистент», менеджер — проверяющий; 👍/👎 и
замечание проверяющего уходят ассистенту с правилами — так он учится.
Наши письма, роботы и ответы в переписке сделки — без ассистента (бесплатно).
""",
    "version": "19.0.1.0.0",
    "category": "Productivity",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_ai", "pmk_mail_ui", "pmk_deal", "pmk_theme"],
    "data": [
        "security/ir.model.access.csv",
        "data/crm_stage.xml",
        "views/triage_views.xml",
        "views/crm_lead_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_ai_mail/static/src/scss/triage.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
