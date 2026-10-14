# -*- coding: utf-8 -*-
{
    # Новые файлы раскроя в Облаке Mail.ru → сообщение в группу Телеграма (15.10.2026).
    #
    # ЗАЧЕМ. Антон: «хочу чтобы при загрузке файлов в определенную папку приходило
    # уведомление в тг» — папка «ПРОИЗВОДСТВО» (подпапки по датам, в них — клиенты),
    # только .dxf, .lxds, .zx (служебные .emf CypCut — не слать).
    #
    # ТОЛЬКО ЧТЕНИЕ. WebDAV Облака (официальный доступ платного тарифа) с паролем для
    # внешнего приложения pmkpark@mail.ru: Odoo смотрит список файлов — не скачивает,
    # не меняет, не удаляет. Пароль — системный параметр, вписывает Антон сам
    # (Настройки → Облако Mail.ru), в репозиторий и в журнал не попадает.
    "name": "ПМК: Облако Mail.ru → Телеграм",
    "version": "19.0.1.0.1",
    "summary": "Новые .dxf/.lxds/.zx в папке Облака Mail.ru — уведомление в группу Телеграма",
    "category": "Productivity",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["base_setup", "pmk_telegram"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/cloud_views.xml",
    ],
    "installable": True,
    "application": False,
}
