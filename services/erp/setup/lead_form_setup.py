"""
Настройка формы Lead для завода металлоконструкций.

Запуск:
    # 1. Скопировать файл в контейнер
    docker cp services/erp/setup/lead_form_setup.py erp-backend-1:/tmp/lead_form_setup.py

    # 2. Выполнить
    docker exec erp-backend-1 bash -c '
      cd /home/frappe/frappe-bench/sites && source ../env/bin/activate && python3 -c "
        import frappe
        frappe.init(site=\"erp.localhost\", sites_path=\".\")
        frappe.connect()
        exec(open(\"/tmp/lead_form_setup.py\").read())
        execute()
        frappe.destroy()
      "'
"""

import frappe

FIELDS_TO_HIDE = [
    # Секция «Основные данные»
    ("salutation", "Lead"),
    ("gender", "Lead"),
    ("lead_type", "Lead"),
    ("last_name", "Lead"),
    ("middle_name", "Lead"),
    ("request_type", "Lead"),
    # Секция «Информация о контакте»
    ("website", "Lead"),
    ("ext", "Lead"),
    # Секция «Организация»
    ("annual_revenue", "Lead"),
    ("no_of_employees", "Lead"),
    ("industry", "Lead"),
    ("market_segment", "Lead"),
    ("fax", "Lead"),
    # Секция «Аналитика»
    ("campaign_name", "Lead"),
    ("medium", "Lead"),
    ("content", "Lead"),
    # Секция «Сертификация»
    ("qualified_by", "Lead"),
    ("qualified_on", "Lead"),
    ("qualification_status", "Lead"),
    # Секция «Дополнительная информация»
    ("language", "Lead"),
    ("unsubscribed", "Lead"),
    ("blog_subscriber", "Lead"),
    ("disabled", "Lead"),
]

CUSTOM_FIELDS = [
    {
        "dt": "Lead",
        "fieldname": "mw_section_break",
        "fieldtype": "Section Break",
        "label": "Металлозавод",
        "insert_after": "market_segment",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_estimated_volume",
        "fieldtype": "Float",
        "label": "Ориентировочный объём (тонн)",
        "insert_after": "mw_section_break",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_desired_delivery_date",
        "fieldtype": "Date",
        "label": "Желаемая дата поставки",
        "insert_after": "mw_estimated_volume",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_drawing_status",
        "fieldtype": "Select",
        "label": "Наличие чертежей",
        "options": "\nЕсть готовые\nНужна разработка\nЧастично",
        "insert_after": "mw_desired_delivery_date",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_project_region",
        "fieldtype": "Data",
        "label": "Регион проекта",
        "insert_after": "mw_drawing_status",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_ai_comment",
        "fieldtype": "Text",
        "label": "AI-комментарий",
        "insert_after": "mw_project_region",
        "read_only": 1,
    },
    {
        "dt": "Lead",
        "fieldname": "mw_note",
        "fieldtype": "Small Text",
        "label": "Примечание",
        "insert_after": "mw_ai_comment",
    },
]


def hide_fields():
    """Скрываем стандартные поля через Property Setter."""
    for fieldname, doctype in FIELDS_TO_HIDE:
        existing = frappe.db.get_value(
            "Property Setter",
            {"doc_type": doctype, "field_name": fieldname, "property": "hidden"},
            "name",
        )
        if existing:
            frappe.db.set_value("Property Setter", existing, "value", "1")
            print(f"  Updated hidden=1 for {doctype}.{fieldname}")
        else:
            frappe.get_doc({
                "doctype": "Property Setter",
                "doctype_or_field": "DocField",
                "doc_type": doctype,
                "field_name": fieldname,
                "property": "hidden",
                "value": "1",
                "property_type": "Check",
            }).insert(ignore_permissions=True)
            print(f"  Set hidden=1 for {doctype}.{fieldname}")


def rename_first_name_label():
    """Переименовываем 'Имя' → 'ФИО'."""
    existing = frappe.db.get_value(
        "Property Setter",
        {"doc_type": "Lead", "field_name": "first_name", "property": "label"},
        "name",
    )
    if existing:
        frappe.db.set_value("Property Setter", existing, "value", "ФИО")
        print("  Updated label for Lead.first_name → ФИО")
    else:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": "Lead",
            "field_name": "first_name",
            "property": "label",
            "value": "ФИО",
            "property_type": "Data",
        }).insert(ignore_permissions=True)
        print("  Set label for Lead.first_name → ФИО")


def add_custom_fields():
    """Добавляем кастомные поля Металлозавода."""
    for field_def in CUSTOM_FIELDS:
        fieldname = field_def["fieldname"]
        if frappe.db.exists("Custom Field", {"dt": "Lead", "fieldname": fieldname}):
            print(f"  Custom field already exists: {fieldname}, skipping")
            continue
        frappe.get_doc({"doctype": "Custom Field", **field_def}).insert(ignore_permissions=True)
        print(f"  Created custom field: {fieldname}")


def execute():
    print("=== Lead Form Setup: Завод металлоконструкций ===")

    print("\n[1/3] Скрытие стандартных полей...")
    hide_fields()

    print("\n[2/3] Переименование поля 'Имя' → 'ФИО'...")
    rename_first_name_label()

    print("\n[3/3] Добавление кастомных полей...")
    add_custom_fields()

    frappe.db.commit()
    print("\nГотово. Перезагрузите страницу ERPNext для применения изменений.")
