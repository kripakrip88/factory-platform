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

# ─── Стандартные поля DocType Lead ────────────────────────────────────────────
FIELDS_TO_HIDE = [
    # Личные данные — нерелевантны для B2B
    ("salutation", "Lead"),
    ("gender", "Lead"),
    ("middle_name", "Lead"),
    ("last_name", "Lead"),
    ("lead_name", "Lead"),           # Full Name — автогенерируемый дубль
    ("first_name", "Lead"),          # перенесён как mw_full_name в блок Contact Info
    # Тип и статус
    ("type", "Lead"),                # Тип Лида (правильный fieldname, не lead_type)
    ("customer", "Lead"),            # From Customer
    ("job_title", "Lead"),           # перемещается в Contact Info через Property Setter
    # Контакты — лишние
    ("phone_ext", "Lead"),           # Внутренний номер (правильный fieldname, не ext)
    ("whatsapp_no", "Lead"),
    ("website", "Lead"),
    # Организация — нерелевантные
    ("annual_revenue", "Lead"),
    ("no_of_employees", "Lead"),
    ("industry", "Lead"),
    ("market_segment", "Lead"),
    ("fax", "Lead"),
    ("territory", "Lead"),           # Территория продаж — нерелевантно при создании
    ("country", "Lead"),             # Страна — всегда Россия
    ("company", "Lead"),             # Наша компания — автозаполняется
    # UTM / Аналитика — все скрываем (utm_source заменён кастомным mw_source)
    ("utm_source", "Lead"),          # оригинал заменён кастомным mw_source
    ("utm_campaign", "Lead"),        # правильный fieldname (не campaign_name)
    ("utm_medium", "Lead"),          # правильный fieldname (не medium)
    ("utm_content", "Lead"),         # правильный fieldname (не content)
    # Секции — скрываем пустые/ненужные
    ("utm_analytics_section", "Lead"),
    ("address_section", "Lead"),
    ("other_info_tab", "Lead"),
    # Сертификация — вся секция и отдельные поля
    ("qualification_tab", "Lead"),
    ("qualified_by", "Lead"),
    ("qualified_on", "Lead"),
    ("qualification_status", "Lead"),
    # Дополнительная информация
    ("language", "Lead"),
    ("unsubscribed", "Lead"),
    ("blog_subscriber", "Lead"),
    ("disabled", "Lead"),
    # Запрос
    ("request_type", "Lead"),
    # Адрес — оригиналы заменены кастомными mw_city / mw_state
    ("city", "Lead"),
    ("state", "Lead"),
]

# ─── Кастомные поля ────────────────────────────────────────────────────────────
CUSTOM_FIELDS = [
    # ── Блок «Информация о контакте» — ФИО + Email / Должность / Телефоны ──
    {
        "dt": "Lead",
        "fieldname": "mw_full_name",
        "fieldtype": "Data",
        "label": "ФИО",
        "reqd": 1,
        "insert_after": "contact_info_tab",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_col_break_contact",
        "fieldtype": "Column Break",
        "insert_after": "mw_full_name",
    },
    # ── Секция «Организация» — правая колонка (Источник, Город, Регион) ──────
    {
        "dt": "Lead",
        "fieldname": "mw_col_break_org",
        "fieldtype": "Column Break",
        "insert_after": "company_name",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_source",
        "fieldtype": "Link",
        "label": "Источник",
        "options": "UTM Source",
        "insert_after": "mw_col_break_org",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_city",
        "fieldtype": "Data",
        "label": "Город",
        "insert_after": "mw_source",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_state",
        "fieldtype": "Data",
        "label": "Регион",
        "insert_after": "mw_city",
    },
    # ── Column Break — разделяет Источник/Город/Регион от Объём/Дата ─────────
    {
        "dt": "Lead",
        "fieldname": "mw_col_break_details",
        "fieldtype": "Column Break",
        "insert_after": "mw_state",
    },
    # ── Секция «Металлозавод» (визуально объединена с Организацией) ──────────
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

# ─── Property Setter для стандартных полей ────────────────────────────────────
# (fieldname, property, value, property_type)
PROPERTY_SETTERS = [
    # Переименовать секцию «Организация» → «Организация и запрос»
    ("organization_section", "label", "Организация и запрос", "Data"),
    # Переместить job_title в блок Contact Info
    ("job_title", "insert_after", "mw_col_break_contact", "Data"),
]

# ─── Кастомные поля — скрытие через Custom Field (не Property Setter) ─────────
# Property Setter hidden=1 не всегда работает для кастомных полей
CUSTOM_FIELDS_TO_HIDE = [
    "mw_section_break",    # убираем разделитель — секции визуально объединяются
    "mw_project_region",   # дублирует mw_state (Регион)
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


def hide_custom_fields():
    """Скрываем кастомные поля напрямую через Custom Field DocType."""
    for fieldname in CUSTOM_FIELDS_TO_HIDE:
        name = frappe.db.get_value("Custom Field", {"dt": "Lead", "fieldname": fieldname}, "name")
        if name:
            frappe.db.set_value("Custom Field", name, "hidden", 1)
            print(f"  Hidden custom field: Lead.{fieldname}")
        else:
            print(f"  Custom field not found: Lead.{fieldname}, skipping")


def apply_property_setters():
    """Применяем Property Setter для перестановок и переименований."""
    for fieldname, prop, value, prop_type in PROPERTY_SETTERS:
        existing = frappe.db.get_value(
            "Property Setter",
            {"doc_type": "Lead", "field_name": fieldname, "property": prop},
            "name",
        )
        if existing:
            frappe.db.set_value("Property Setter", existing, "value", value)
            print(f"  Updated {prop} for Lead.{fieldname} → {value}")
        else:
            frappe.get_doc({
                "doctype": "Property Setter",
                "doctype_or_field": "DocField",
                "doc_type": "Lead",
                "field_name": fieldname,
                "property": prop,
                "value": value,
                "property_type": prop_type,
            }).insert(ignore_permissions=True)
            print(f"  Set {prop} for Lead.{fieldname} → {value}")


def add_custom_fields():
    """Добавляем кастомные поля."""
    for field_def in CUSTOM_FIELDS:
        fieldname = field_def["fieldname"]
        if frappe.db.exists("Custom Field", {"dt": "Lead", "fieldname": fieldname}):
            print(f"  Custom field already exists: {fieldname}, skipping")
            continue
        frappe.get_doc({"doctype": "Custom Field", **field_def}).insert(ignore_permissions=True)
        print(f"  Created custom field: {fieldname}")


def execute():
    print("=== Lead Form Layout: Завод металлоконструкций ===")

    print("\n[1/4] Скрытие стандартных полей...")
    hide_fields()

    print("\n[2/4] Скрытие кастомных полей...")
    hide_custom_fields()

    print("\n[3/4] Добавление кастомных полей...")
    add_custom_fields()

    print("\n[4/4] Property Setter: переименования и перестановки...")
    apply_property_setters()

    frappe.db.commit()
    print("\n✅ Готово. Перезагрузите страницу ERPNext для применения изменений.")
