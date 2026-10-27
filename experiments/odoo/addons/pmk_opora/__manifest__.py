# -*- coding: utf-8 -*-
{
    # Опоры трубопроводов (Антон 25.10.2026): калькулятор как у фундаментных болтов
    # (pmk_bolt) + справочник. Стандарт — свой файл tools/<стандарт>.py и docs/<стандарт>.md,
    # правятся отдельно (tools/catalog.py — диспетчер): ОСТ 36-146-88 (КП, КХ), ОСТ 36-94-83 (ОПП1).
    # Масса — по фактическим деталям; состав — лист по прайсам, болты и гайки покупные;
    # наценку ставит менеджер (в строке или «Ценовая политика», вид «Опоры трубопроводов»).
    "name": "ПМК: опоры трубопроводов",
    "version": "19.0.1.3.0",  # 19.0.1.1.0 — ОСТ 36-94-83 (ОПП1), стандарты по файлам; 19.0.1.2.0 — в расчёт изделием «Конструкций»; 19.0.1.3.0 — чертежи марки (в.2)
    "summary": "Калькулятор и справочник опор трубопроводов: ОСТ 36-146-88 (КП, КХ), ОСТ 36-94-83 (ОПП1)",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_bolt", "pmk_calc", "pmk_bridge", "pmk_butik", "crm"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/opora_views.xml",
        "views/ref_views.xml",
        "views/menus.xml",
        "data/ref_fill.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_opora/static/src/js/opora_grid.js",
            "pmk_opora/static/src/xml/opora_grid.xml",
            "pmk_opora/static/src/scss/opora_grid.scss",
            "pmk_opora/static/src/js/opora_drawing.js",
            "pmk_opora/static/src/xml/opora_drawing.xml",
            "pmk_opora/static/src/scss/opora_drawing.scss",
        ],
    },
    "installable": True,
}
