"""
Номенклатура металлопроката — Вариант А (партионный учёт длин).
Схема: одна позиция = профиль + марка стали. Длина хлыста — в Batch.

Запуск: bench --site erp.localhost execute erpnext.nomenclature_setup.execute
Идемпотентен.
"""

import frappe

# ── Номенклатура ──────────────────────────────────────────────────────────────

ITEMS = [
    {
        "item_code":       "УГ-50х50х5-С245",
        "item_name":       "Уголок 50х50х5 С245",
        "item_group":      "Сортовой прокат",
        "weight_per_unit": 3.77,
        "painting_area":   0.19,
    },
    {
        "item_code":       "ШВ-10-С245",
        "item_name":       "Швеллер 10 С245",
        "item_group":      "Сортовой прокат",
        "weight_per_unit": 8.59,
        "painting_area":   0.36,
    },
    {
        "item_code":       "ТП-40х40х3-С245",
        "item_name":       "Труба профильная 40х40х3 С245",
        "item_group":      "Сортовой прокат",
        "weight_per_unit": 3.45,
        "painting_area":   0.16,
    },
    {
        "item_code":       "ТК-57х3-С245",
        "item_name":       "Труба круглая 57х3 С245",
        "item_group":      "Сортовой прокат",
        "weight_per_unit": 3.97,
        "painting_area":   0.18,
    },
]

# Тестовые партии для первой номенклатуры
TEST_BATCHES = [
    {"item_code": "УГ-50х50х5-С245", "batch_id": "УГ-50х50х5-С245-12000", "length_mm": 12000},
    {"item_code": "УГ-50х50х5-С245", "batch_id": "УГ-50х50х5-С245-6000",  "length_mm": 6000},
    {"item_code": "УГ-50х50х5-С245", "batch_id": "УГ-50х50х5-С245-3700",  "length_mm": 3700},
]

# Старые шаблоны и варианты для удаления
OLD_ITEMS = [
    "Уголок 50х50х5-12000", "Уголок 50х50х5-11700", "Уголок 50х50х5-6000",
    "Швеллер 10-12000",      "Швеллер 10-11700",      "Швеллер 10-6000",
    "Труба профильная 40х40х3-12000", "Труба профильная 40х40х3-11700", "Труба профильная 40х40х3-6000",
    "Труба круглая 57х3-12000",       "Труба круглая 57х3-11700",       "Труба круглая 57х3-6000",
    "Уголок 50х50х5", "Швеллер 10", "Труба профильная 40х40х3", "Труба круглая 57х3",
]


# ── Вспомогательные функции ───────────────────────────────────────────────────

def ensure_custom_field(doctype, fieldname, label, fieldtype, insert_after=None):
    exists = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname})
    if not exists:
        doc = frappe.get_doc({
            "doctype":      "Custom Field",
            "dt":           doctype,
            "fieldname":    fieldname,
            "label":        label,
            "fieldtype":    fieldtype,
            "insert_after": insert_after or "description",
        })
        doc.insert(ignore_permissions=True)
        return True
    return False


def delete_old_items():
    deleted = 0
    for code in OLD_ITEMS:
        if not frappe.db.exists("Item", code):
            continue
        # Удаляем складские остатки если есть (иначе ERPNext не даст удалить)
        frappe.db.delete("Bin",              {"item_code": code})
        frappe.db.delete("Stock Ledger Entry", {"item_code": code})
        frappe.db.delete("Item Price",       {"item_code": code})
        frappe.delete_doc("Item", code, ignore_permissions=True, force=True)
        deleted += 1
    return deleted


def create_item(data, painting_cf_exists):
    code = data["item_code"]
    if frappe.db.exists("Item", code):
        # Обновляем painting_area если поле уже есть
        if painting_cf_exists:
            frappe.db.set_value("Item", code, "painting_area", data["painting_area"])
        return False

    doc = frappe.get_doc({
        "doctype":         "Item",
        "item_code":       code,
        "item_name":       data["item_name"],
        "item_group":      data["item_group"],
        "stock_uom":       "шт",
        "is_stock_item":   1,
        "has_variants":    0,
        "has_batch_no":    1,
        "create_new_batch": 0,
        "weight_per_unit": data["weight_per_unit"],
        "weight_uom":      "кг",
    })
    doc.insert(ignore_permissions=True)

    if painting_cf_exists:
        frappe.db.set_value("Item", code, "painting_area", data["painting_area"])

    return True


def create_batch(item_code, batch_id, length_mm, length_cf_exists):
    if frappe.db.exists("Batch", batch_id):
        return False
    doc = frappe.get_doc({
        "doctype":   "Batch",
        "batch_id":  batch_id,
        "item":      item_code,
    })
    doc.insert(ignore_permissions=True)
    if length_cf_exists:
        frappe.db.set_value("Batch", batch_id, "length_mm", length_mm)
    return True


# ── Точка входа ───────────────────────────────────────────────────────────────

def execute():
    frappe.db.begin()

    # 1. Кастомные поля
    painting_cf = ensure_custom_field(
        "Item", "painting_area", "Площадь покраски (м²/м)", "Float", "weight_uom"
    )
    length_cf = ensure_custom_field(
        "Batch", "length_mm", "Длина (мм)", "Int", "description"
    )
    frappe.db.commit()

    # 2. Удаляем старые варианты
    deleted = delete_old_items()
    frappe.db.commit()

    # 3. Создаём новую номенклатуру
    created_items = sum(create_item(d, True) for d in ITEMS)
    frappe.db.commit()

    # 4. Создаём тестовые партии
    created_batches = sum(
        create_batch(b["item_code"], b["batch_id"], b["length_mm"], True)
        for b in TEST_BATCHES
    )
    frappe.db.commit()

    print(f"\n✅ Номенклатура настроена (Вариант А — партионный учёт):")
    print(f"   Кастомное поле Item.painting_area:  {'создано' if painting_cf else 'уже было'}")
    print(f"   Кастомное поле Batch.length_mm:     {'создано' if length_cf else 'уже было'}")
    print(f"   Старых записей удалено: {deleted}")
    print(f"   Номенклатур создано:    {created_items}")
    print(f"   Тестовых партий создано: {created_batches}")
