# -*- coding: utf-8 -*-
{
    "name": "ПМК Парк — Калькуляторы",
    "summary": "Расчёт металлопроката и доборных элементов",
    "description": """
Калькуляторы ПМК Парк, перенесённые с ERPNext.

Справочник сортамента — табличные значения ГОСТ, а не расчёт по сечению:
массы подняты из официальных таблиц и кросс-проверены по двум источникам.
Исключение — гладкий лист, там масса 1 м² и есть толщина × 7.85 по
ГОСТ 19903-2015.

Контрольные якоря на случай, если данные поедут при переносе:
  Двутавр 20Б1 = 21.3 кг/м, Швеллер 16У = 14.2, Уголок 50x50x5 = 3.77,
  Труба круглая 159x6 = 22.64, Лист 4 мм = 31.4 кг/м².

Модуль намеренно НЕ зависит от склада: справочник свой, чтобы калькулятор
работал до того, как будет решён вопрос платформы и загружена номенклатура.
Переключение на позиции системы — отдельным шагом.
""",
    # Версию поднимаем не для красоты: по ней Odoo решает, запускать ли скрипты
    # из migrations/. 19.0.1.0.1 — пересчёт хранимых эскизов доборки, см.
    # migrations/19.0.1.0.1/post-migrate.py. 19.0.1.0.4 — история расчётов и
    # доборок по-русски (разбор UX, шаг 30). 19.0.1.0.5 — «Создано: Расчёт
    # металлопроката» в старой истории и имя нумератора СМ- (шаг 39: слово
    # документа — «расчёт», «спецификация» — только чертёж клиента).
    # 19.0.1.0.6 — отпечаток раскладки у уже разложенных расчётов (шаг 56:
    # сигнал «Раскладка устарела»; разложенные до 30.09 — «могла устареть»).
    "version": "19.0.1.0.6",
    "category": "Manufacturing",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        # Шаг З-10: сотрудник заводит позицию справочника только «на разнос».
        "security/pending_rules.xml",
        "data/pmk.metal.grade.csv",
        "data/pmk.metal.profile.type.csv",
        # Шаг З-10: вид проката «Прочее» для позиций «на разнос».
        "data/pending_data.xml",
        "data/pmk.metal.profile.csv",
        "data/pmk.metal.sheet.csv",
        "data/pmk.metal.fastener.csv",
        "data/pmk.paint.coating.csv",
        "data/pmk.dobor.coating.csv",
        "data/ir_sequence.xml",
        "views/metal_views.xml",
        "views/metal_spec_views.xml",
        "views/dobor_views.xml",
        # Шаг З-10: окна «Новая позиция на разнос», формы справочника с
        # «Принять в справочник», список «Новые позиции на разнос».
        "views/pending_views.xml",
        "report/dobor_report.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pmk_calc/static/src/scss/dobor_builder.scss",
            "pmk_calc/static/src/js/dobor_builder.js",
            "pmk_calc/static/src/js/dobor_dialog_fullscreen.js",
            "pmk_calc/static/src/js/svg_field.js",
            "pmk_calc/static/src/js/product_lines_field.js",
            # Шаг З-10: «Нет в справочнике — завести новую…» в выпадашке
            # позиции детали, метка «на разнос».
            "pmk_calc/static/src/js/pending_create.js",
            "pmk_calc/static/src/xml/dobor_builder.xml",
            "pmk_calc/static/src/xml/svg_field.xml",
            "pmk_calc/static/src/xml/product_lines_field.xml",
            # Приёмка 01.10.2026: форма расчёта без «Новое» (R6), дата
            # словами в заголовке (R3), «Копировать» у позиции доборки (R9b).
            "pmk_calc/static/src/js/spec_form_view.js",
            "pmk_calc/static/src/js/long_date_field.js",
            "pmk_calc/static/src/scss/spec_form.scss",
            "pmk_calc/static/src/js/dobor_copy_line.js",
            "pmk_calc/static/src/xml/dobor_copy_line.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
    "auto_install": False,
}
