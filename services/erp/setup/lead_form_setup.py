"""
Настройка формы Lead для завода металлоконструкций.

Скрипт выполняет ПОЛНЫЙ ПЕРЕСБОР: удаляет все существующие Custom Field
и Property Setter для Lead, затем создаёт всё заново в правильном порядке.

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
    [TOP]
      Серия | — | Владелец Лида | Статус

    [Информация о контакте]
      ФИО *     | Email          | Телефон
      Должность | Мобильный      |

    [Организация и запрос]
      Название орг. * | Источник
                      | Город
                      | Регион
      ─────────────────────────────
      Объём (тонн)    | Дата поставки
      ─────────────────────────────
      Наличие чертежей
      AI-комментарий
      Примечание

Примечание о синхронизации mw_full_name → first_name:
    first_name используется ERPNext внутренне для построения lead_name.
    Добавить Client Script (ERPNext Admin → Client Script):

    frappe.ui.form.on('Lead', {
        mw_full_name: function(frm) {
            frm.set_value('first_name', frm.doc.mw_full_name);
        }
    });
"""

import frappe

# ─── Кастомные поля — создаются в указанном порядке ───────────────────────────
CUSTOM_FIELDS = [
    # ── Блок «Информация о контакте» ─────────────────────────────────────────
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
        "fieldname": "mw_cb_contact",          # col break: ФИО+Должность | Email+Мобильный
        "fieldtype": "Column Break",
        "label": "",
        "insert_after": "mw_job_title",
    },
    # email_id, mobile_no — стандартные, встают в col2 автоматически
    {
        "fieldname": "mw_cb_contact2",         # col break: Email+Мобильный | Телефон
        "fieldtype": "Column Break",
        "label": "",
        "insert_after": "mobile_no",
    },
    # phone — стандартный, встаёт в col3 автоматически

    # ── Блок «Организация и запрос» ───────────────────────────────────────────
    # company_name — стандартное, col1
    {
        "fieldname": "mw_cb_org",              # col break: Название орг. | Источник
        "fieldtype": "Column Break",
        "label": "",
        "insert_after": "company_name",
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
    # Section Break без label — "переносит строку": Объём/Дата встают под Название орг.
    {
        "fieldname": "mw_sb_details",
        "fieldtype": "Section Break",
        "label": "",
        "insert_after": "mw_state",
    },
    {
        "fieldname": "mw_estimated_volume",
        "fieldtype": "Float",
        "label": "Ориентировочный объём (тонн)",
        "insert_after": "mw_sb_details",
    },
    {
        "fieldname": "mw_cb_details",          # col break: Объём | Дата поставки
        "fieldtype": "Column Break",
        "label": "",
        "insert_after": "mw_estimated_volume",
    },
    {
        "fieldname": "mw_desired_delivery_date",
        "fieldtype": "Date",
        "label": "Желаемая дата поставки",
        "insert_after": "mw_cb_details",
    },
    # Section Break без label — широкие поля на всю ширину
    {
        "fieldname": "mw_sb_wide",
        "fieldtype": "Section Break",
        "label": "",
        "insert_after": "mw_desired_delivery_date",
    },
    {
        "fieldname": "mw_drawing_status",
        "fieldtype": "Select",
        "label": "Наличие чертежей",
        "options": "\nЕсть готовые\nНужна разработка\nЧастично",
        "insert_after": "mw_sb_wide",
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
]

# ─── Стандартные поля — скрыть через Property Setter ──────────────────────────
FIELDS_TO_HIDE = [
    # Личные данные
    "salutation", "gender", "middle_name", "last_name", "lead_name",
    # Тип / статус
    "type", "customer", "request_type",
    # Заменены кастомными
    "first_name", "job_title",
    # Контакты — лишние
    "phone_ext", "whatsapp_no", "website",
    # Организация — нерелевантные
    "annual_revenue", "no_of_employees", "industry", "market_segment", "fax",
    # UTM — заменён mw_source; остальные не нужны
    "utm_campaign", "utm_medium", "utm_content", "utm_source",
    # Секции — пустые/ненужные
    "utm_analytics_section", "address_section", "other_info_tab",
    # Сертификация
    "qualification_tab", "qualified_by", "qualified_on", "qualification_status",
    # Доп. информация
    "language", "unsubscribed", "blog_subscriber", "disabled",
    # Адрес — заменён кастомными mw_city / mw_state
    "city", "state", "country", "territory",
    # Наша компания — автозаполняется
    "company",
]

# ─── Property Setter: переименования ──────────────────────────────────────────
# (fieldname, property, value, property_type)
LABEL_OVERRIDES = [
    ("organization_section", "label", "Организация и запрос", "Data"),
]


def _delete_existing():
    """Удаляем все старые Custom Field и Property Setter для Lead."""
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
        print(f"  created: {fd['fieldname']} ({fd['fieldtype']})")


def _apply_property_setters():
    for fieldname in FIELDS_TO_HIDE:
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

    for fieldname, prop, value, prop_type in LABEL_OVERRIDES:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": "Lead",
            "field_name": fieldname,
            "property": prop,
            "value": value,
            "property_type": prop_type,
        }).insert(ignore_permissions=True)
        print(f"  {prop}: {fieldname} → '{value}'")


def execute():
    print("=== Lead Form Setup: Завод металлоконструкций ===")

    print("\n[1/3] Удаляем старые настройки...")
    _delete_existing()

    print("\n[2/3] Создаём кастомные поля...")
    _create_custom_fields()

    print("\n[3/3] Property Setter: скрытие и переименования...")
    _apply_property_setters()

    frappe.db.commit()
    print("\n✅ Готово. Перезагрузите страницу ERPNext (Ctrl+R).")
