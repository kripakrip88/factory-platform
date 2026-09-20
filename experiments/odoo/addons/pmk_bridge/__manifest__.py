# -*- coding: utf-8 -*-
{
    # Мост между справочником pmk_calc и номенклатурой Odoo. Нужен потому, что
    # цена поставщика (product.supplierinfo) требует товар, а сортамент лежит в
    # собственных таблицах pmk_calc и товаром не является.
    #
    # Модуль намеренно НЕ ставится автоматически. Он несёт СРЕДУ под
    # номенклатуру (коды ОКЕИ, дерево категорий, две характеристики), а сами
    # 752 карточки заводит скрипт scripts/load_products.py: карточки — данные
    # завода, а не данные модуля, и переустановка модуля не должна их трогать.
    "name": "ПМК: мост справочника в номенклатуру",
    "version": "19.0.0.1.0",
    "summary": "Артикулы (default_code) для переноса сортамента pmk_calc в товары",
    "category": "Inventory/Inventory",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # Каждая зависимость проверена по базе стенда, а не взята на память:
    #   product, uom      — товары, единицы, характеристики;
    #   stock             — склад, партии (кусок проката = партия);
    #   stock_account     — способ учёта затрат и оценка запасов на категориях
    #                       (property_cost_method / property_valuation);
    #   l10n_ru_doc       — поле uom.uom.kod (field_uom_uom__kod принадлежит ему);
    #   l10n_ru_upd_xml   — поле uom.uom.okei, без него УПД не выгрузится;
    #   pmk_calc          — сам справочник, из которого растут карточки.
    "depends": [
        "product",
        "uom",
        "stock",
        "stock_account",
        "l10n_ru_doc",
        "l10n_ru_upd_xml",
        "pmk_calc",
    ],
    # data/uom_by_category.csv сюда КЛАСТЬ НЕЛЬЗЯ: это не данные модели, а
    # таблица соответствий «категория — единица», её читают скрипты.
    #
    # ГРАБЛЯ ПРО ОКЕИ: коды лягут только при ПЕРВОЙ установке. Обновление
    # модуля (-u pmk_bridge) их не перепишет — orm/models.py::_load_records
    # пропускает запись, если у ЦЕЛЕВОЙ строки в ir_model_data стоит
    # noupdate, а модуль uom грузит свои единицы именно так. Если коды
    # поменяются — гонять scripts/prepare_environment.py, он грузит файл
    # в режиме init.
    "data": [
        "data/uom_okei.xml",
        "data/product_category.xml",
        "data/product_attribute.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
