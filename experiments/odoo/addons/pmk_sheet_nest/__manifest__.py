# -*- coding: utf-8 -*-
{
    "name": "ПМК Парк — Раскрой листа",
    "summary": "Вкладка «Раскрой листа» в задании лазеру: раскладка DXF на лист, 4 порядка резки, программа CypCut",
    "description": """
Раскрой деталей задания лазеру на лист: раскладка, сравнение четырёх порядков
резки (холостой ход, опасные переходы, возврат к нулю), программа CypCut (.lxds),
которая принимается в задание тем же разбором pmk_laser.

Движок — пакет sheet_nest (lib/sheet_nest), его ведёт отдельный чат, ветка
feature/sheet-nest-lib; правки lib/ — только там. Обмен — контракт sheet_nest.job/1
(experiments/sheet_nest/ERP.md). Пока пакета в lib/ нет — заглушка stub/stub_job.py:
экран и путь работают, программа не собирается.

Считает отдельный процесс (runner.py), как у pmk_vent_nest: у воркеров Odoo предел
240 с на запрос. Очередь общая с раскроем вентзонтов — на сервере одновременно
считается один раскрой.
""",
    "version": "19.0.0.1.1",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # pmk_vent_nest — ради общей очереди (models/run.py, VentNestJobQueue) и пакета
    # vent_nesting, на котором стоит раскладка sheet_nest.
    "depends": ["pmk_laser", "pmk_vent_nest", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/laser_job_views.xml",
        "views/laser_nest_views.xml",
        "views/laser_machine_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_sheet_nest/static/src/scss/sheet_nest.scss",
            "pmk_sheet_nest/static/src/js/strategy_pick.js",
            "pmk_sheet_nest/static/src/xml/strategy_pick.xml",
            "pmk_sheet_nest/static/src/js/nest_programs.js",
            "pmk_sheet_nest/static/src/xml/nest_programs.xml",
        ],
    },
    "installable": True,
}
