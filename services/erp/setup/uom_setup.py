"""
UOM Setup — единицы измерения, склады, группы номенклатуры, атрибуты.
Запуск: bench --site erp.localhost execute /tmp/uom_setup.py
Идемпотентен: существующие записи пропускаются.
"""

import frappe


def create_uoms():
    uoms = [
        {"uom_name": "тн", "must_be_whole_number": 0, "description": "Тонна"},
        {"uom_name": "шт", "must_be_whole_number": 1, "description": "Штука"},
        {"uom_name": "м",  "must_be_whole_number": 0, "description": "Погонный метр"},
        {"uom_name": "мм", "must_be_whole_number": 0, "description": "Миллиметр"},
        {"uom_name": "м²", "must_be_whole_number": 0, "description": "Квадратный метр"},
        {"uom_name": "кг", "must_be_whole_number": 0, "description": "Килограмм"},
    ]
    created = 0
    for data in uoms:
        if not frappe.db.exists("UOM", data["uom_name"]):
            doc = frappe.get_doc({"doctype": "UOM", **data})
            doc.insert(ignore_permissions=True)
            created += 1
    return created


def create_uom_conversions():
    conversions = [
        {"from_uom": "тн", "to_uom": "кг", "value": 1000},
        {"from_uom": "м",  "to_uom": "мм", "value": 1000},
    ]
    created = 0
    for data in conversions:
        exists = frappe.db.exists(
            "UOM Conversion Factor",
            {"from_uom": data["from_uom"], "to_uom": data["to_uom"]},
        )
        if not exists:
            doc = frappe.get_doc({"doctype": "UOM Conversion Factor", **data})
            doc.insert(ignore_permissions=True)
            created += 1
    return created


def create_warehouses():
    company = frappe.defaults.get_global_default("company")
    main_warehouse = f"All Warehouses - {frappe.get_cached_value('Company', company, 'abbr')}"

    warehouses = [
        {"warehouse_name": "Металлопрокат", "parent_warehouse": main_warehouse},
        {"warehouse_name": "Обрезки",        "parent_warehouse": main_warehouse},
        {"warehouse_name": "Готовая продукция", "parent_warehouse": main_warehouse},
        {"warehouse_name": "Брак",           "parent_warehouse": main_warehouse},
    ]
    created = 0
    for data in warehouses:
        abbr = frappe.get_cached_value("Company", company, "abbr")
        wh_name = f"{data['warehouse_name']} - {abbr}"
        if not frappe.db.exists("Warehouse", wh_name):
            doc = frappe.get_doc({
                "doctype": "Warehouse",
                "warehouse_name": data["warehouse_name"],
                "parent_warehouse": data["parent_warehouse"],
                "company": company,
            })
            doc.insert(ignore_permissions=True)
            created += 1
    return created


def create_item_groups():
    groups = [
        {"item_group_name": "Металлопрокат",               "parent_item_group": "All Item Groups"},
        {"item_group_name": "Сортовой прокат",              "parent_item_group": "Металлопрокат"},
        {"item_group_name": "Листовой прокат",              "parent_item_group": "Металлопрокат"},
        {"item_group_name": "Трубы",                        "parent_item_group": "Металлопрокат"},
        {"item_group_name": "Метизы",                       "parent_item_group": "Металлопрокат"},
        {"item_group_name": "Обрезки",                      "parent_item_group": "All Item Groups"},
        {"item_group_name": "Готовая продукция",            "parent_item_group": "All Item Groups"},
    ]
    created = 0
    for data in groups:
        if not frappe.db.exists("Item Group", data["item_group_name"]):
            doc = frappe.get_doc({"doctype": "Item Group", **data})
            doc.insert(ignore_permissions=True)
            created += 1
    return created


def create_length_attribute():
    if not frappe.db.exists("Item Attribute", "Длина"):
        doc = frappe.get_doc({
            "doctype": "Item Attribute",
            "attribute_name": "Длина",
            "numeric_values": 1,
            "from_range": 0,
            "to_range": 100000,
            "increment": 1,
        })
        doc.insert(ignore_permissions=True)
        return 1
    return 0


def execute():
    frappe.db.begin()

    uoms = create_uoms()
    conversions = create_uom_conversions()
    warehouses = create_warehouses()
    groups = create_item_groups()
    attributes = create_length_attribute()

    frappe.db.commit()

    print(f"\n✅ UOM Setup завершён:")
    print(f"   Единицы измерения: {uoms} создано")
    print(f"   Коэффициенты конвертации: {conversions} создано")
    print(f"   Склады: {warehouses} создано")
    print(f"   Группы номенклатуры: {groups} создано")
    print(f"   Атрибуты: {attributes} создано")
