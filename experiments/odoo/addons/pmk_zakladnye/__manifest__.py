# -*- coding: utf-8 -*-
{
    # Закладные изделия МН по сериям 1.400-15 и 1.400-6/76 (Антон 25.10.2026): отдельный
    # калькулятор рядом с фундаментными болтами. Марка коротко («мн 201-5 12шт») → состав
    # и масса сразу; чертёж PDF (2 листа А3) — фоновым процессом (worker/, свой образ
    # с PyMuPDF); DXF пластин и шайб — в zip и в задание на резку → «Раскрой листа».
    # Генератор — lib/ (перенос из сессии «Закладные МН», логика не тронута).
    # Сшивка с расчётом, КП и ценами — потом, отдельным шагом (решение Антона).
    "name": "ПМК: закладные изделия",
    "version": "19.0.1.0.0",
    "summary": "Закладные МН по сериям 1.400-15 и 1.400-6/76: состав, масса, чертежи PDF, DXF для лазера",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["pmk_calc", "pmk_butik", "pmk_deal", "pmk_laser", "crm", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/zk_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_zakladnye/static/src/js/zk_grid.js",
            "pmk_zakladnye/static/src/xml/zk_grid.xml",
            "pmk_zakladnye/static/src/scss/zk_grid.scss",
        ],
    },
    "installable": True,
}
