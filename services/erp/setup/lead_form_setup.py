"""
Настройка формы Lead для завода металлоконструкций.

Скрипт выполняет ПОЛНЫЙ ПЕРЕСБОР: удаляет все существующие Custom Field
и Property Setter для Lead, затем создаёт всё заново в правильном порядке.
Client Script для синхронизации mw_full_name/mw_job_title создаётся/обновляется.

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
    [без секции]
      Серия | Владелец | Статус

    [Контакт]
      ФИО *     | Email     | Телефон
      Должность | Мобильный |

    [Организация и запрос]
      Название орг. *       | Источник
      Объём (тонн)          | Город
      Желаемая дата поставки| Регион
      Наличие чертежей      |
      AI-комментарий
      Примечание
"""

import frappe

# ─── Стандартные поля — скрыть через Property Setter ──────────────────────────
HIDE_STANDARD = [
    # Личные данные
    "salutation", "gender", "middle_name", "last_name", "lead_name",
    "first_name",    # заменён кастомным mw_full_name
    "job_title",     # заменён кастомным mw_job_title
    # Тип / статус
    "type", "customer", "request_type",
    # Контакты — лишние
    "phone_ext", "whatsapp_no", "website",
    # Организация — нерелевантные
    "annual_revenue", "no_of_employees", "industry", "market_segment", "fax",
    # UTM — заменён mw_source; остальные не нужны
    "utm_source", "utm_campaign", "utm_medium", "utm_content",
    # Секции — пустые/ненужные
    "utm_analytics_section", "address_section", "other_info_tab",
    # Сертификация
    "qualification_tab", "qualified_by", "qualified_on", "qualification_status",
    # Доп. информация
    "language", "unsubscribed", "blog_subscriber", "disabled",
    # Адрес — заменён кастомными mw_city / mw_state
    "city", "state", "country", "territory",
    # Наша компания
    "company",
]

# Стандартные Column Break которые ломают сетку — скрыть
HIDE_COLUMN_BREAKS = [
    "col_break123",    # TOP: пустая средняя колонка
    "column_break_20", # Contact: разрыв между email и mobile
    "column_break_16", # Contact: разрыв перед phone
    "column_break_28", # Org: пустой col2
    "column_break_31", # Org: пустой col3
]

# ─── Property Setter: переименования + insert_after для стандартных полей ─────
RENAMES = [
    ("organization_section", "label",        "Организация и запрос"),
    ("contact_info_tab",     "label",        "Контакт"),
    # TOP: lead_owner/status после нашего mw_cb_top (col_break123 скрыт)
    ("lead_owner",           "insert_after", "mw_cb_top"),
    ("status",               "insert_after", "lead_owner"),
    # Contact: email → mobile → phone в одной колонке (column_break_20/16 скрыты)
    ("mobile_no",            "insert_after", "email_id"),
    ("phone",                "insert_after", "mobile_no"),
]

# ─── Кастомные поля — создаются в указанном порядке ───────────────────────────
CUSTOM_FIELDS = [
    # ── TOP: Column Break после series → lead_owner/status в col2 ─────────────
    {
        "fieldname": "mw_cb_top",
        "fieldtype": "Column Break",
        "insert_after": "series",
    },
    # ── Блок «Контакт» ────────────────────────────────────────────────────────
    {
        "fieldname": "mw_full_name",
        "fieldtype": "Data",
        "label": "ФИО",
        "reqd": 1,
        "insert_after": "contact_info_tab",
    },
    {
        "fieldname": "mw_job_title",
        "fieldtype": "Data",
        "label": "Должность",
        "insert_after": "mw_full_name",
    },
    {
        "fieldname": "mw_cb_contact",      # col break → email, mobile в col2
        "fieldtype": "Column Break",
        "insert_after": "mw_job_title",
    },
    # email_id, mobile_no → col2; mw_cb_contact2 отделяет phone → col3
    # (col2/col3 формируются скрытием стандартных column_break_20 и column_break_16)

    # ── Блок «Организация и запрос» — левая колонка ───────────────────────────
    # company_name — стандартное, col1
    {
        "fieldname": "mw_estimated_volume",
        "fieldtype": "Float",
        "label": "Объём (тонн)",
        "insert_after": "company_name",
    },
    {
        "fieldname": "mw_desired_delivery_date",
        "fieldtype": "Date",
        "label": "Желаемая дата поставки",
        "insert_after": "mw_estimated_volume",
    },
    {
        "fieldname": "mw_drawing_status",
        "fieldtype": "Select",
        "label": "Наличие чертежей",
        "options": "\nЕсть готовые\nНужна разработка\nЧастично",
        "insert_after": "mw_desired_delivery_date",
    },
    {
        "fieldname": "mw_ai_comment",
        "fieldtype": "Text",
        "label": "AI-комментарий",
        "read_only": 1,
        "insert_after": "mw_drawing_status",
    },
    {
        "fieldname": "mw_note",
        "fieldtype": "Small Text",
        "label": "Примечание",
        "insert_after": "mw_ai_comment",
    },
    # ── Блок «Организация и запрос» — правая колонка ─────────────────────────
    {
        "fieldname": "mw_cb_org",          # col break → Источник/Город/Регион в col2
        "fieldtype": "Column Break",
        "insert_after": "mw_note",
    },
    {
        "fieldname": "mw_source",
        "fieldtype": "Link",
        "label": "Источник",
        "options": "UTM Source",
        "insert_after": "mw_cb_org",
    },
    {
        "fieldname": "mw_city",
        "fieldtype": "Data",
        "label": "Город",
        "insert_after": "mw_source",
    },
    {
        "fieldname": "mw_state",
        "fieldtype": "Data",
        "label": "Регион",
        "insert_after": "mw_city",
    },
]

# ─── Client Script: синхронизация кастомных полей со стандартными ─────────────
CLIENT_SCRIPT_NAME = "Lead-Form"
CLIENT_SCRIPT = """\
frappe.ui.form.on('Lead', {
    mw_full_name: function(frm) {
        frm.set_value('first_name', frm.doc.mw_full_name);
    },
    mw_job_title: function(frm) {
        frm.set_value('job_title', frm.doc.mw_job_title);
    }
});
"""


def _delete_existing():
    old_cfs = frappe.get_all("Custom Field", filters={"dt": "Lead"}, pluck="name")
    for name in old_cfs:
        frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
    print(f"  удалено Custom Field: {len(old_cfs)}")

    old_ps = frappe.get_all("Property Setter", filters={"doc_type": "Lead"}, pluck="name")
    for name in old_ps:
        frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
    print(f"  удалено Property Setter: {len(old_ps)}")

    frappe.db.commit()


def _create_custom_fields():
    for fd in CUSTOM_FIELDS:
        frappe.get_doc({"doctype": "Custom Field", "dt": "Lead", **fd}).insert(ignore_permissions=True)
        print(f"  + {fd['fieldname']} ({fd['fieldtype']})")


def _apply_property_setters():
    for fieldname in HIDE_STANDARD + HIDE_COLUMN_BREAKS:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": "Lead",
            "field_name": fieldname,
            "property": "hidden",
            "value": "1",
            "property_type": "Check",
        }).insert(ignore_permissions=True)
        print(f"  hidden: {fieldname}")

    for fieldname, prop, value in RENAMES:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": "Lead",
            "field_name": fieldname,
            "property": prop,
            "value": value,
            "property_type": "Data",
        }).insert(ignore_permissions=True)
        print(f"  rename: {fieldname} → '{value}'")


def _upsert_client_script():
    existing = frappe.db.get_value("Client Script", {"dt": "Lead"}, "name")
    if existing:
        doc = frappe.get_doc("Client Script", existing)
        doc.script = CLIENT_SCRIPT
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        print(f"  обновлён: {existing}")
    else:
        frappe.get_doc({
            "doctype": "Client Script",
            "name": CLIENT_SCRIPT_NAME,
            "dt": "Lead",
            "view": "Form",
            "enabled": 1,
            "script": CLIENT_SCRIPT,
        }).insert(ignore_permissions=True)
        print(f"  создан: {CLIENT_SCRIPT_NAME}")


def execute():
    print("=== Lead Form Setup: Завод металлоконструкций ===")

    print("\n[1/4] Удаляем старые настройки...")
    _delete_existing()

    print("\n[2/4] Создаём кастомные поля...")
    _create_custom_fields()

    print("\n[3/4] Property Setter: скрытие и переименования...")
    _apply_property_setters()

    frappe.db.commit()

    print("\n[4/4] Client Script...")
    _upsert_client_script()

    frappe.db.commit()
    print("\n✅ Готово. Перезагрузите страницу ERPNext (Ctrl+R).")
