# -*- coding: utf-8 -*-
{
    # Просмотр чертежей DXF в браузере, без АвтоКАДа и Компаса (разбор
    # удобства, шаг 46, просьба Антона 01.10.2026; решение 05.10 — в этом
    # шаге только DXF, 3D-модели и DWG — отдельным шагом).
    #
    # Одно окно на всю систему:
    #   • лента любого документа (расчёт, задание лазеру, сделка) — щелчок по
    #     вложению .dxf открывает чертёж, а не «ничего» (штатный просмотрщик
    #     Odoo DXF не умеет);
    #   • задание лазеру — кнопка «Посмотреть» у детали (pmk_laser);
    #   • почта и файл .dxf из архива — то же окно внутри «Посмотреть» почты
    #     (vendor/mail_client берёт его из реестра pmk_file_viewers).
    #
    # Разбор и отрисовка — готовой библиотекой ezdxf 1.4.2 (MIT, стоит в
    # образе: experiments/odoo/Dockerfile, ARG PYDEPS), отдельным процессом
    # с пределами памяти и времени (tools/dxf_render.py). Браузер получает
    # готовые пути SVG по слоям и только показывает: масштаб колесом к
    # курсору, сдвиг перетаскиванием, «Вписать», слои галочками.
    #
    # ЗАВИСИМОСТИ — только web и mail. Почта и лазер сами спрашивают, стоит
    # ли этот модуль ('pmk.drawing' in env), — без жёсткой связи: удаление
    # модуля не снесёт ни почту, ни лазер каскадом, а там окно скажет
    # «Просмотр DXF недоступен». ezdxf НЕ объявлен внешней зависимостью по
    # той же причине: без него модуль ставится, а окно честно пишет, что
    # библиотеки на сервере нет (образ пересобрали без неё).
    #
    # Первая установка на стенд: INSTALL="pmk_drawing" sh deploy.sh
    # (в OURS deploy.sh модуль есть — дальше обновляется сам).
    "name": "ПМК: просмотр чертежей DXF",
    "version": "19.0.1.0.0",
    "summary": "Чертёж DXF в браузере: масштаб, сдвиг, слои — из ленты, почты и лазера",
    "category": "Productivity",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["web", "mail"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            # Чистые правила вида — первыми: их импортируют окно и патч ленты.
            "pmk_drawing/static/src/js/dxf_view_math.js",
            "pmk_drawing/static/src/js/dxf_viewer.js",
            "pmk_drawing/static/src/js/dxf_dialog.js",
            "pmk_drawing/static/src/js/attachment_list_patch.js",
            "pmk_drawing/static/src/xml/dxf_viewer.xml",
            # Карточка .dxf в ленте — курсор-лупа и «посмотреть чертёж».
            "pmk_drawing/static/src/xml/attachment_list.xml",
            "pmk_drawing/static/src/scss/dxf_viewer.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
