"""
CRM, часть 1/3: справочник «Категория изделий» + заводские поля на лиде и сделке.

Идемпотентно создаёт:
  1. DocType «MW Product Category» — справочник категорий изделий (7 стартовых).
  2. DocType «MW Product Category Item» — child-таблица (Link на справочник),
     общая для Lead и Opportunity → Table MultiSelect.
  3. Custom Field «Категория изделий» (Table MultiSelect) на Lead и Opportunity.
  4. На Opportunity — секцию «Параметры заявки» и поля 1:1 с лидом
     (mw_estimated_volume / mw_desired_delivery_date / mw_drawing_status),
     чтобы get_mapped_doc переносил их штатно при создании сделки из лида.

Перенос данных лид→сделка (полностью штатным get_mapped_doc, без кода):
  - Скалярные поля (объём/дата/чертежи) — get_mapped_doc копирует поля с
    одинаковым fieldname автоматически.
  - Табличное поле категорий — get_mapped_doc копирует child-таблицу
    автоматически, т.к. на лиде и сделке ОДИН и тот же fieldname
    (mw_product_categories) и ОДИН child-доктайп (MW Product Category Item),
    без no_copy (frappe/model/mapper.py, авто-маппинг таблиц по fieldname+options).
  Поэтому одинаковые fieldname на обоих доктайпах — намеренное условие переноса.

Запуск:
    docker cp services/erp/setup/crm_product_categories.py \
      erp-backend-1:/tmp/crm_product_categories.py
    docker exec erp-backend-1 bash -c "cd /home/frappe/frappe-bench && \
      bench --site erp.localhost execute /tmp/crm_product_categories.py"
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CATEGORY_DOCTYPE = "MW Product Category"
CATEGORY_ITEM_DOCTYPE = "MW Product Category Item"

CATEGORIES = [
    "Фундаментные болты",
    "Закладные детали",
    "Армокаркасы",
    "Металлоконструкции",
    "Металлоизделия",
    "Доборные элементы",
    "ЭБК",
]

DRAWING_OPTIONS = "\nЕсть готовые\nНужна разработка\nЧастично"


def create_category_doctype():
    """Справочник категорий изделий (custom DocType)."""
    if frappe.db.exists("DocType", CATEGORY_DOCTYPE):
        return False
    frappe.get_doc({
        "doctype": "DocType",
        "name": CATEGORY_DOCTYPE,
        "module": "Custom",
        "custom": 1,
        "autoname": "field:category_name",
        "title_field": "category_name",
        "track_changes": 1,
        "sort_field": "category_name",
        "sort_order": "ASC",
        "fields": [
            {
                "fieldname": "category_name",
                "label": "Категория",
                "fieldtype": "Data",
                "reqd": 1,
                "unique": 1,
                "in_list_view": 1,
            }
        ],
        "permissions": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Sales Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Sales User", "read": 1},
        ],
    }).insert(ignore_permissions=True)
    return True


def create_category_item_doctype():
    """Child-таблица для Table MultiSelect (общая для Lead и Opportunity)."""
    if frappe.db.exists("DocType", CATEGORY_ITEM_DOCTYPE):
        return False
    frappe.get_doc({
        "doctype": "DocType",
        "name": CATEGORY_ITEM_DOCTYPE,
        "module": "Custom",
        "custom": 1,
        "istable": 1,
        "fields": [
            {
                "fieldname": "product_category",
                "label": "Категория изделий",
                "fieldtype": "Link",
                "options": CATEGORY_DOCTYPE,
                "reqd": 1,
                "in_list_view": 1,
            }
        ],
    }).insert(ignore_permissions=True)
    return True


def seed_categories():
    created = 0
    for name in CATEGORIES:
        if not frappe.db.exists(CATEGORY_DOCTYPE, name):
            frappe.get_doc({
                "doctype": CATEGORY_DOCTYPE,
                "category_name": name,
            }).insert(ignore_permissions=True)
            created += 1
    return created


def setup_custom_fields():
    """Table MultiSelect на лиде/сделке + заводские поля 1:1 на сделке."""
    fields = {
        "Lead": [
            {
                "fieldname": "mw_product_categories",
                "label": "Категория изделий",
                "fieldtype": "Table MultiSelect",
                "options": CATEGORY_ITEM_DOCTYPE,
                "insert_after": "company_name",
            },
        ],
        "Opportunity": [
            {
                "fieldname": "mw_request_params_section",
                "label": "Параметры заявки",
                "fieldtype": "Section Break",
                "insert_after": "territory",
            },
            {
                "fieldname": "mw_product_categories",
                "label": "Категория изделий",
                "fieldtype": "Table MultiSelect",
                "options": CATEGORY_ITEM_DOCTYPE,
                "insert_after": "mw_request_params_section",
            },
            {
                "fieldname": "mw_estimated_volume",
                "label": "Объём (тонн)",
                "fieldtype": "Float",
                "insert_after": "mw_product_categories",
            },
            {
                "fieldname": "mw_desired_delivery_date",
                "label": "Желаемая дата поставки",
                "fieldtype": "Date",
                "insert_after": "mw_estimated_volume",
            },
            {
                "fieldname": "mw_drawing_status",
                "label": "Наличие чертежей",
                "fieldtype": "Select",
                "options": DRAWING_OPTIONS,
                "insert_after": "mw_desired_delivery_date",
            },
        ],
    }
    create_custom_fields(fields, ignore_validate=True)

    # На лиде поставить категорию ПЕРЕД объёмом: блок «что за заявка» =
    # Категория → Объём → Дата → … → Наличие чертежей. mw_estimated_volume
    # исходно insert_after=company_name — перецепляем его за новое поле.
    if frappe.db.exists("Custom Field", "Lead-mw_estimated_volume"):
        frappe.db.set_value(
            "Custom Field", "Lead-mw_estimated_volume",
            "insert_after", "mw_product_categories",
        )


def execute():
    dt_cat = create_category_doctype()
    dt_item = create_category_item_doctype()
    seeded = seed_categories()
    setup_custom_fields()
    frappe.db.commit()
    frappe.clear_cache()

    print("=== CRM: категории изделий + поля лид/сделка ===")
    print(f"DocType «{CATEGORY_DOCTYPE}»: {'создан' if dt_cat else 'уже был'}")
    print(f"DocType «{CATEGORY_ITEM_DOCTYPE}»: {'создан' if dt_item else 'уже был'}")
    print(f"Категорий добавлено: {seeded} (всего в справочнике: {frappe.db.count(CATEGORY_DOCTYPE)})")
    print("Custom Fields на Lead и Opportunity применены (идемпотентно).")
    print("Готово.")
