"""
Импорт шаблонов номенклатуры и вариантов сортового проката.
Запуск: bench --site erp.localhost execute erpnext.import_nomenclature.execute
Идемпотентен: существующие записи пропускаются.
"""

import frappe
from erpnext.controllers.item_variant import create_variant

TEMPLATES = [
    {"code": "Уголок 50х50х5",          "paint": 0.19},
    {"code": "Швеллер 10",               "paint": 0.36},
    {"code": "Труба профильная 40х40х3", "paint": 0.16},
    {"code": "Труба круглая 57х3",       "paint": 0.18},
]

LENGTHS     = [6000, 11700, 12000]
STEEL_GRADE = "С245"
GROUP       = "Сортовой прокат"
UOM         = "шт"


def _attr_meta(attribute_name):
    """Читаем numeric_values и диапазон из Item Attribute чтобы правильно заполнить дочернюю таблицу."""
    return frappe.db.get_value(
        "Item Attribute",
        attribute_name,
        ["numeric_values", "from_range", "to_range", "increment"],
        as_dict=True,
    ) or {}


def create_template(code):
    if frappe.db.exists("Item", code):
        # Обновляем numeric_values в существующих дочерних строках если они неправильные
        for attr_name in ["Длина", "Площадь покраски (м²/м)", "Марка стали"]:
            meta = _attr_meta(attr_name)
            frappe.db.set_value(
                "Item Variant Attribute",
                {"attribute": attr_name, "parent": code},
                {
                    "numeric_values": meta.get("numeric_values", 0),
                    "from_range":     meta.get("from_range", 0),
                    "to_range":       meta.get("to_range", 0),
                    "increment":      meta.get("increment", 0),
                },
            )
        return False

    attrs = []
    for attr_name in ["Марка стали", "Длина", "Площадь покраски (м²/м)"]:
        meta = _attr_meta(attr_name)
        attrs.append({
            "attribute":     attr_name,
            "numeric_values": meta.get("numeric_values", 0),
            "from_range":    meta.get("from_range", 0),
            "to_range":      meta.get("to_range", 0),
            "increment":     meta.get("increment", 0),
        })

    doc = frappe.get_doc({
        "doctype": "Item",
        "item_code": code,
        "item_name": code,
        "item_group": GROUP,
        "stock_uom": UOM,
        "has_variants": 1,
        "attributes": attrs,
    })
    doc.insert(ignore_permissions=True)
    return True


def create_item_variant(template_code, length, paint):
    variant_code = f"{template_code}-{length}"
    if frappe.db.exists("Item", variant_code):
        return False

    variant = create_variant(template_code, {
        "Марка стали":             STEEL_GRADE,
        "Длина":                   str(length),
        "Площадь покраски (м²/м)": str(paint),
    })
    variant.item_code = variant_code
    variant.item_name = variant_code
    variant.insert(ignore_permissions=True)
    return True


def execute():
    templates_created = 0
    variants_created  = 0

    for t in TEMPLATES:
        if create_template(t["code"]):
            templates_created += 1

    frappe.db.commit()

    for t in TEMPLATES:
        for length in LENGTHS:
            if create_item_variant(t["code"], length, t["paint"]):
                variants_created += 1

    frappe.db.commit()

    print(f"\n✅ Номенклатура импортирована:")
    print(f"   Шаблоны: {templates_created} создано")
    print(f"   Варианты: {variants_created} создано")
