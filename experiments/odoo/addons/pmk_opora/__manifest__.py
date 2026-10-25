# -*- coding: utf-8 -*-
{
    # Опоры трубопроводов (Антон 25.10.2026): калькулятор как у фундаментных болтов
    # (pmk_bolt) + справочник. Стандарт — свой файл tools/<стандарт>.py и docs/<стандарт>.md,
    # правятся отдельно (tools/catalog.py — диспетчер): ОСТ 36-146-88 (КП, КХ), ОСТ 36-94-83 (ОПП1).
    # Масса — по фактическим деталям; состав — лист по прайсам, болты и гайки покупные;
    # наценка — «Ценовая политика» (вид «Опоры трубопроводов»).
    "name": "ПМК: опоры трубопроводов",
    "version": "19.0.1.1.0",  # 19.0.1.1.0 — ОСТ 36-94-83 (ОПП1), стандарты по файлам
    "summary": "Калькулятор и справочник опор трубопроводов: ОСТ 36-146-88 (КП, КХ), ОСТ 36-94-83 (ОПП1)",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_bolt", "pmk_calc", "pmk_bridge", "pmk_butik", "crm"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/policy.xml",
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
        ],
    },
    "installable": True,
}
