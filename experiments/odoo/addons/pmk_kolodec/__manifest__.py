# -*- coding: utf-8 -*-
{
    # Металлоизделия колодцев (Антон 25.10.2026): калькулятор как у болтов и опор + справочник.
    # Альбом — свой файл tools/<альбом>.py и раздел docs/, правятся отдельно (tools/catalog.py —
    # диспетчер): 902-09-22.84 ал. VII (стремянки С1, ЗО, К1), 901-09-11.84 ал. V (стремянки С,
    # МН1), ал. VI.88 (МС-1…8), ал. II (проставки монтажные — эскиз).
    # Масса — по фактическим деталям; состав — прокат и лист по прайсам, покупное вписывают;
    # наценка — «Ценовая политика» (вид «Металлоизделия колодцев»).
    "name": "ПМК: металлоизделия колодцев",
    "version": "19.0.1.1.0",  # 19.0.1.1.0 — полоса = лист, поправка на гиб в настройках
    "summary": "Калькулятор и справочник: стремянки, элементы МС, скоба МН1, проставки, ЗО, К1 по ТПР 901-09-11.84 и 902-09-22.84",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_bolt", "pmk_calc", "pmk_bridge", "pmk_butik", "crm"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/policy.xml",
        "data/bend.xml",
        "views/kolodec_views.xml",
        "views/ref_views.xml",
        "views/bend_views.xml",
        "views/menus.xml",
        "data/ref_fill.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_kolodec/static/src/js/kolodec_grid.js",
            "pmk_kolodec/static/src/xml/kolodec_grid.xml",
            "pmk_kolodec/static/src/scss/kolodec_grid.scss",
        ],
    },
    "installable": True,
}
