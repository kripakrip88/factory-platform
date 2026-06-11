"""
Настройка CRM для завода металлоконструкций.

Запуск:
    docker compose -f services/erp/docker-compose.yml cp \
      services/erp/setup/crm_setup.py backend:/tmp/crm_setup.py
    docker compose -f services/erp/docker-compose.yml exec backend \
      bench --site erp.localhost execute /tmp/crm_setup.py
"""

import frappe

OPPORTUNITY_TYPES = ["Продажи", "Поддержка", "Обслуживание"]

SALES_STAGES = [
    "Новый запрос",
    "Квалификация",
    "Расчёт КП",
    "КП отправлено",
    "Переговоры",
    "Победа",
    "Проигрыш",
]

OPPORTUNITY_PROPERTY_SETTERS = [
    ("opportunity_type",    "hidden", "1"),
    ("expected_closing",    "reqd",   "0"),
    ("expected_closing",    "hidden", "1"),
    ("probability",         "hidden", "1"),
    ("campaign",            "hidden", "1"),
    ("source",              "hidden", "1"),
    ("contact_display",     "hidden", "1"),
    ("customer_address",    "hidden", "1"),
    ("address_display",     "hidden", "1"),
    ("with_items",          "hidden", "1"),
    ("items_section",       "hidden", "1"),
    ("competitors_section", "hidden", "1"),
    ("terms_section",       "hidden", "1"),
]

# Секции sidebar CRM которые отключаем (вместе со всеми дочерними ссылками).
# Sidebar определяется в Workspace Sidebar DocType (source: erpnext/workspace_sidebar/crm.json).
REMOVE_SIDEBAR_SECTIONS = {"Reports", "Maintenance", "Sales Pipeline", "Campaign"}


# Создаём типы сделок даже если поле скрыто —
# дефолтное значение "Продажи" валидируется при сохранении документа
def setup_opportunity_types():
    created = 0
    for ot in OPPORTUNITY_TYPES:
        if not frappe.db.exists("Opportunity Type", ot):
            frappe.get_doc({"doctype": "Opportunity Type", "name": ot}).insert(ignore_permissions=True)
            created += 1
    frappe.db.commit()
    return created


def setup_sales_stages():
    created = 0
    for stage_name in SALES_STAGES:
        if not frappe.db.exists("Sales Stage", stage_name):
            doc = frappe.get_doc({
                "doctype": "Sales Stage",
                "stage_name": stage_name,
            })
            doc.insert(ignore_permissions=True)
            created += 1
    frappe.db.commit()
    return created


def apply_property_setters():
    applied = 0
    for fieldname, prop, value in OPPORTUNITY_PROPERTY_SETTERS:
        ps_name = f"Opportunity-{fieldname}-{prop}"
        if frappe.db.exists("Property Setter", ps_name):
            frappe.db.set_value("Property Setter", ps_name, "value", value)
        else:
            frappe.get_doc({
                "doctype": "Property Setter",
                "doctype_or_field": "DocField",
                "doc_type": "Opportunity",
                "field_name": fieldname,
                "property": prop,
                "property_type": "Check" if prop in ("hidden", "reqd") else "Data",
                "value": value,
            }).insert(ignore_permissions=True)
        applied += 1
    frappe.db.commit()
    return applied


def cleanup_crm_workspace():
    """Отключает лишние секции из бокового меню CRM через Workspace Sidebar."""
    if not frappe.db.exists("Workspace Sidebar", "CRM"):
        print("Workspace Sidebar 'CRM' not found — skipping")
        return 0

    ws = frappe.get_doc("Workspace Sidebar", "CRM")
    original_count = len(ws.items)

    # Удалить items с пустым label (вызывают null crash в JS)
    ws.items = [item for item in ws.items if item.label and item.label.strip()]

    keep = []
    in_removed_section = False

    for item in ws.items:
        if item.type == "Section Break":
            in_removed_section = item.label in REMOVE_SIDEBAR_SECTIONS
            if not in_removed_section:
                keep.append(item)
        elif not in_removed_section:
            keep.append(item)

    ws.items = keep
    ws.save(ignore_permissions=True)
    frappe.clear_cache()

    removed = original_count - len(keep)
    print(f"Sidebar: отключено {removed} элементов, осталось {len(keep)}")
    return removed


def execute():
    types_created = setup_opportunity_types()
    stages_created = setup_sales_stages()
    setters_applied = apply_property_setters()
    sidebar_removed = cleanup_crm_workspace()

    print("=== CRM Setup ===")
    print(f"Типов сделки создано: {types_created}")
    print(f"Этапов воронки создано: {stages_created} (пропущено существующих: {len(SALES_STAGES) - stages_created})")
    print(f"Property Setter применено: {setters_applied}")
    print(f"Sidebar: отключено элементов: {sidebar_removed}")
    print("Готово.")
