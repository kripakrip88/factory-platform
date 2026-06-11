"""
Номенклатура металлопроката — гибридная схема.

Склад Металлопрокат: шаблоны + варианты по атрибуту Длина (6000/11700/12000 мм).
Склад Обрезки:       отдельные номенклатуры с суффиксом -ОБР, учёт через Batch.

Запуск: bench --site erp.localhost execute erpnext.nomenclature_setup.execute
Идемпотентен.
"""

import frappe
from erpnext.controllers.item_variant import create_variant

# ── Данные ────────────────────────────────────────────────────────────────────

TEMPLATES = [
    {"code": "УГ-50х50х5-С245",   "name": "Уголок 50х50х5 С245",            "kg_m": 3.77, "paint": 0.19},
    {"code": "ШВ-10-С245",        "name": "Швеллер 10 С245",                 "kg_m": 8.59, "paint": 0.36},
    {"code": "ТП-40х40х3-С245",   "name": "Труба профильная 40х40х3 С245",   "kg_m": 3.45, "paint": 0.16},
    {"code": "ТК-57х3-С245",      "name": "Труба круглая 57х3 С245",         "kg_m": 3.97, "paint": 0.18},
]

LENGTHS = [6000, 11700, 12000]

COMPANY_ABBR   = "ЗМК"
WH_METAL       = f"Металлопрокат - {COMPANY_ABBR}"
WH_SCRAP       = f"Обрезки - {COMPANY_ABBR}"
GROUP_METAL    = "Сортовой прокат"
GROUP_SCRAP    = "Обрезки"

# Все коды для сброса (старые + текущие)
ALL_ITEM_CODES = (
    [t["code"] for t in TEMPLATES]
    + [f"{t['code']}-{l}" for t in TEMPLATES for l in LENGTHS]
    + [f"{t['code']}-ОБР" for t in TEMPLATES]
    # legacy batch-only items из предыдущей итерации
    + ["УГ-50х50х5-С245", "ШВ-10-С245", "ТП-40х40х3-С245", "ТК-57х3-С245"]
)


# ── Шаг 0: очистка ────────────────────────────────────────────────────────────

def delete_old_data():
    codes = list(dict.fromkeys(ALL_ITEM_CODES))  # дедупликация с сохранением порядка
    deleted = 0
    for code in codes:
        if not frappe.db.exists("Item", code):
            continue
        frappe.db.delete("Stock Ledger Entry", {"item_code": code})
        frappe.db.delete("Bin",                {"item_code": code})
        frappe.db.delete("Item Price",         {"item_code": code})
        frappe.db.delete("Batch",              {"item": code})
        frappe.delete_doc("Item", code, ignore_permissions=True, force=True)
        deleted += 1
    # Удаляем незакрытые Stock Entry (только черновики)
    for se in frappe.get_all("Stock Entry", filters={"docstatus": 0}, pluck="name"):
        frappe.delete_doc("Stock Entry", se, ignore_permissions=True, force=True)
    return deleted


# ── Шаг 1: шаблоны ───────────────────────────────────────────────────────────

def _fix_numeric_attr(item_code, attr_name):
    """Копирует numeric_values/range из Item Attribute в дочернюю строку шаблона."""
    meta = frappe.db.get_value(
        "Item Attribute", attr_name,
        ["numeric_values", "from_range", "to_range", "increment"],
        as_dict=True,
    ) or {}
    frappe.db.set_value(
        "Item Variant Attribute",
        {"attribute": attr_name, "parent": item_code},
        {
            "numeric_values": meta.get("numeric_values", 0),
            "from_range":     meta.get("from_range", 0),
            "to_range":       meta.get("to_range", 0),
            "increment":      meta.get("increment", 0),
        },
    )


def create_template(t):
    doc = frappe.get_doc({
        "doctype":      "Item",
        "item_code":    t["code"],
        "item_name":    t["name"],
        "item_group":   GROUP_METAL,
        "stock_uom":    "шт",
        "is_stock_item": 1,
        "has_variants": 1,
        "weight_per_unit": t["kg_m"],
        "weight_uom":   "кг",
        "attributes":   [{"attribute": "Длина"}],
    })
    doc.insert(ignore_permissions=True)
    _fix_numeric_attr(t["code"], "Длина")
    frappe.db.set_value("Item", t["code"], "painting_area", t["paint"])
    return True


# ── Шаг 2: варианты ──────────────────────────────────────────────────────────

def create_item_variant(tmpl, length):
    variant_code = f"{tmpl['code']}-{length}"
    weight = round(tmpl["kg_m"] * length / 1000, 2)

    variant = create_variant(tmpl["code"], {"Длина": str(length)})
    variant.item_code        = variant_code
    variant.item_name        = variant_code
    variant.weight_per_unit  = weight
    variant.weight_uom       = "кг"
    variant.insert(ignore_permissions=True)
    frappe.db.set_value("Item", variant_code, "painting_area", tmpl["paint"])
    return True


# ── Шаг 3: номенклатуры обрезков ─────────────────────────────────────────────

def create_scrap_item(t):
    code = f"{t['code']}-ОБР"
    name = f"{t['name'].replace(' С245', '')} С245 Обрезок"
    doc = frappe.get_doc({
        "doctype":       "Item",
        "item_code":     code,
        "item_name":     name,
        "item_group":    GROUP_SCRAP,
        "stock_uom":     "шт",
        "is_stock_item": 1,
        "has_variants":  0,
        "has_batch_no":  1,
        "create_new_batch": 0,
        "weight_uom":    "кг",
    })
    doc.insert(ignore_permissions=True)
    frappe.db.set_value("Item", code, "painting_area", t["paint"])
    return True


# ── Шаг 4: тестовые остатки ──────────────────────────────────────────────────

def create_test_stock():
    scrap_item  = "УГ-50х50х5-С245-ОБР"

    # Создаём партию для обрезка
    batch_id = f"{scrap_item}-1700"
    if not frappe.db.exists("Batch", batch_id):
        b = frappe.get_doc({"doctype": "Batch", "batch_id": batch_id, "item": scrap_item})
        b.insert(ignore_permissions=True)
        frappe.db.set_value("Batch", batch_id, "length_mm", 1700)

    se = frappe.get_doc({
        "doctype":            "Stock Entry",
        "stock_entry_type":   "Material Receipt",
        "items": [
            {
                "item_code":           "УГ-50х50х5-С245-6000",
                "qty":                 5,
                "t_warehouse":         WH_METAL,
                "uom":                 "шт",
                "conversion_factor":   1,
                "basic_rate":                0,
                "allow_zero_valuation_rate": 1,
            },
            {
                "item_code":           "УГ-50х50х5-С245-12000",
                "qty":                 4,
                "t_warehouse":         WH_METAL,
                "uom":                 "шт",
                "conversion_factor":   1,
                "basic_rate":                0,
                "allow_zero_valuation_rate": 1,
            },
            {
                "item_code":           scrap_item,
                "qty":                 2,
                "t_warehouse":         WH_SCRAP,
                "uom":                 "шт",
                "conversion_factor":   1,
                "basic_rate":                0,
                "allow_zero_valuation_rate": 1,
                "batch_no":            batch_id,
            },
        ],
    })
    se.insert(ignore_permissions=True)
    se.submit()
    return se.name


# ── Точка входа ───────────────────────────────────────────────────────────────

def execute():
    frappe.db.begin()

    deleted = delete_old_data()
    frappe.db.commit()

    for t in TEMPLATES:
        create_template(t)
    frappe.db.commit()

    variants_created = 0
    for t in TEMPLATES:
        for length in LENGTHS:
            create_item_variant(t, length)
            variants_created += 1
    frappe.db.commit()

    for t in TEMPLATES:
        create_scrap_item(t)
    frappe.db.commit()

    se_name = create_test_stock()
    frappe.db.commit()

    print(f"\n✅ Номенклатура металлопроката настроена (гибридная схема):")
    print(f"   Старых записей удалено:  {deleted}")
    print(f"   Шаблонов создано:        {len(TEMPLATES)}")
    print(f"   Вариантов создано:       {variants_created}")
    print(f"   Номенклатур обрезков:    {len(TEMPLATES)}")
    print(f"   Тестовое поступление:    {se_name}")
