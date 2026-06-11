"""
Импорт шаблонов номенклатуры и вариантов сортового проката.
Запуск: bench --site erp.localhost execute erpnext.import_nomenclature.execute
Идемпотентен: существующие записи пропускаются.
"""

import frappe

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


def create_template(code):
    if frappe.db.exists("Item", code):
        return False
    doc = frappe.get_doc({
        "doctype": "Item",
        "item_code": code,
        "item_name": code,
        "item_group": GROUP,
        "stock_uom": UOM,
        "has_variants": 1,
        "attributes": [
            {"attribute": "Марка стали"},
            {"attribute": "Длина"},
            {"attribute": "Площадь покраски (м²/м)"},
        ],
    })
    doc.insert(ignore_permissions=True)
    return True


def create_variant(template_code, length, paint):
    variant_code = f"{template_code}-{length}"
    if frappe.db.exists("Item", variant_code):
        return False

    doc = frappe.get_doc({
        "doctype": "Item",
        "item_code": variant_code,
        "item_name": variant_code,
        "item_group": GROUP,
        "stock_uom": UOM,
        "variant_of": template_code,
        "attributes": [
            {"attribute": "Марка стали",              "attribute_value": STEEL_GRADE},
            {"attribute": "Длина",                    "attribute_value": str(length)},
            {"attribute": "Площадь покраски (м²/м)",  "attribute_value": str(paint)},
        ],
    })
    doc.insert(ignore_permissions=True)
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
            if create_variant(t["code"], length, t["paint"]):
                variants_created += 1

    frappe.db.commit()

    print(f"\n✅ Номенклатура импортирована:")
    print(f"   Шаблоны: {templates_created} создано")
    print(f"   Варианты: {variants_created} создано")
