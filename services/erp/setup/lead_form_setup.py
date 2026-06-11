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

Целевой макет:
    [TOP]           Серия | Владелец | Статус
    [Contact Info]  ФИО * | email
                    Должность | Мобильный | Телефон
    [Орг и запрос]  Название орг * | Источник
                                   | Город
                                   | Регион
                    Объём  | Дата поставки
                    Чертежи |
                    AI-комментарий
                    Примечание
"""

import frappe

# ─── Стандартные поля — скрыть через Property Setter ──────────────────────────
FIELDS_TO_HIDE = [
    # Личные данные — нерелевантны для B2B
    ("salutation", "Lead"),
    ("gender", "Lead"),
    ("middle_name", "Lead"),
    ("last_name", "Lead"),
    ("lead_name", "Lead"),           # Full Name — автогенерируемый дубль
    ("first_name", "Lead"),          # перенесён как mw_full_name в Contact Info
    # Тип и статус
    ("type", "Lead"),                # Тип Лида (правильный fieldname, не lead_type)
    ("customer", "Lead"),            # From Customer
    ("job_title", "Lead"),           # перенесён как mw_job_title в Contact Info
    # Контакты — лишние
    ("phone_ext", "Lead"),           # Внутренний номер
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
    # UTM / Аналитика — utm_source заменён кастомным mw_source
    ("utm_source", "Lead"),
    ("utm_campaign", "Lead"),
    ("utm_medium", "Lead"),
    ("utm_content", "Lead"),
    # Секции — пустые/ненужные
    ("utm_analytics_section", "Lead"),
    ("address_section", "Lead"),
    ("other_info_tab", "Lead"),
    # Сертификация
    ("qualification_tab", "Lead"),
    ("qualified_by", "Lead"),
    ("qualified_on", "Lead"),
    ("qualification_status", "Lead"),
    # Дополнительная информация
    ("language", "Lead"),
    ("unsubscribed", "Lead"),
    ("blog_subscriber", "Lead"),
    ("disabled", "Lead"),
    # Прочее
    ("request_type", "Lead"),
    ("city", "Lead"),                # оригинал заменён кастомным mw_city
    ("state", "Lead"),               # оригинал заменён кастомным mw_state
]

# ─── Кастомные поля — скрыть напрямую через Custom Field DocType ───────────────
CUSTOM_FIELDS_TO_HIDE = [
    "mw_section_break",    # разделитель убран — секции объединяются визуально
    "mw_project_region",   # дублирует mw_state (Регион)
]

# ─── Property Setter: переименования, перестановки, insert_after ───────────────
# (fieldname, property, value, property_type)
PROPERTY_SETTERS = [
    # Переименовать секцию «Организация» → «Организация и запрос»
    ("organization_section", "label",        "Организация и запрос", "Data"),
    # Перепривязать mw_* — убрать зависимость от скрытого mw_section_break
    ("mw_estimated_volume",      "insert_after", "mw_state",               "Data"),
    ("mw_col_break_details",     "insert_after", "mw_estimated_volume",    "Data"),
    ("mw_desired_delivery_date", "insert_after", "mw_col_break_details",   "Data"),
    ("mw_drawing_status",        "insert_after", "mw_desired_delivery_date","Data"),
    ("mw_ai_comment",            "insert_after", "mw_drawing_status",      "Data"),
    ("mw_note",                  "insert_after", "mw_ai_comment",          "Data"),
    # Перепривязать Column Break в Contact Info — после mw_job_title
    ("mw_col_break_contact",     "insert_after", "mw_job_title",           "Data"),
]

# ─── Кастомные поля — создать если не существуют ──────────────────────────────
CUSTOM_FIELDS = [
    # ── Contact Info: ФИО (левая колонка) ──────────────────────────────────
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
        "fieldname": "mw_job_title",
        "fieldtype": "Data",
        "label": "Должность",
        "insert_after": "mw_full_name",
    },
    {
        "dt": "Lead",
        "fieldname": "mw_col_break_contact",
        "fieldtype": "Column Break",
        "insert_after": "mw_job_title",
    },
    # ── Contact Info: Column Break между email и телефонами ─────────────────
    {
        "dt": "Lead",
        "fieldname": "mw_col_break_contact2",
        "fieldtype": "Column Break",
        "insert_after": "email_id",
    },
    # ── Организация: правая колонка (Источник / Город / Регион) ────────────
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
    # ── Организация: поля запроса (через Column Break — двухколоночные) ─────
    {
        "dt": "Lead",
        "fieldname": "mw_col_break_details",
        "fieldtype": "Column Break",
        "insert_after": "mw_state",
    },
    # ── Section Break «Металлозавод» — создаём, но сразу скрываем ──────────
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


def hide_custom_fields():
    """Скрываем кастомные поля напрямую через Custom Field DocType."""
    for fieldname in CUSTOM_FIELDS_TO_HIDE:
        name = frappe.db.get_value("Custom Field", {"dt": "Lead", "fieldname": fieldname}, "name")
        if name:
            frappe.db.set_value("Custom Field", name, "hidden", 1)
            print(f"  Hidden custom field: Lead.{fieldname}")
        else:
            print(f"  Custom field not found: Lead.{fieldname}, skipping")


def add_custom_fields():
    """Добавляем кастомные поля."""
    for field_def in CUSTOM_FIELDS:
        fieldname = field_def["fieldname"]
        if frappe.db.exists("Custom Field", {"dt": "Lead", "fieldname": fieldname}):
            print(f"  Custom field already exists: {fieldname}, skipping")
            continue
        frappe.get_doc({"doctype": "Custom Field", **field_def}).insert(ignore_permissions=True)
        print(f"  Created custom field: {fieldname}")


def apply_property_setters():
    """Применяем Property Setter: переименования, перестановки, insert_after."""
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


def execute():
    print("=== Lead Form Setup: Завод металлоконструкций ===")

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
