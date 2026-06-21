"""
CRM: карточка канбана сделок — осмысленные данные.

Заголовок карточки = организация/клиент (customer_name, не email в title).
Поля карточки = Категория изделий (текст), Объём (тонн), Сумма сделки, Дата касания.
Убраны «Создано» (owner) и «Статус» (дублирует колонку канбана).

Категория (mw_product_categories) — Table MultiSelect; Frappe-канбан НЕ выводит
значение child-таблицы. Поэтому зеркалим её в текстовое поле mw_categories_display
(Small Text, read-only, hidden на форме) — его и кладём в поля карточки. Синк —
на validate Opportunity (saas_theme.crm.sync_categories_display, doc_events).

Идемпотентно. Запуск (bench console):
  import runpy; runpy.run_path('/tmp/crm_kanban.py')['execute']()
"""

import json
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

KANBAN_BOARD = "Продажи"
CARD_FIELDS = ["mw_categories_display", "mw_estimated_volume", "opportunity_amount", "modified"]


def setup_display_field():
    """Текстовое зеркало категорий для канбана (Table MultiSelect не рендерится)."""
    create_custom_fields({
        "Opportunity": [
            {
                "fieldname": "mw_categories_display",
                "label": "Категория изделий",
                "fieldtype": "Small Text",
                "read_only": 1,
                "hidden": 1,
                "no_copy": 0,
                "insert_after": "mw_product_categories",
            },
        ],
    }, ignore_validate=True)


def backfill_categories_display():
    """Заполнить mw_categories_display у существующих сделок (без триггера save)."""
    n = 0
    for name in frappe.get_all("Opportunity", pluck="name"):
        rows = frappe.get_all(
            "MW Product Category Item",
            filters={"parent": name, "parenttype": "Opportunity", "parentfield": "mw_product_categories"},
            pluck="product_category",
        )
        frappe.db.set_value("Opportunity", name, "mw_categories_display", ", ".join(rows), update_modified=False)
        n += 1
    return n


def set_title_field():
    """Заголовок Opportunity = customer_name (организация), не title с email."""
    ps_name = "Opportunity-main-title_field"
    if frappe.db.exists("Property Setter", ps_name):
        frappe.db.set_value("Property Setter", ps_name, "value", "customer_name")
        return "обновлён"
    frappe.get_doc({
        "doctype": "Property Setter",
        "doctype_or_field": "DocType",
        "doc_type": "Opportunity",
        "property": "title_field",
        "property_type": "Data",
        "value": "customer_name",
    }).insert(ignore_permissions=True)
    return "создан"


def set_kanban_fields():
    if not frappe.db.exists("Kanban Board", KANBAN_BOARD):
        return f"доска «{KANBAN_BOARD}» не найдена — пропуск"
    frappe.db.set_value("Kanban Board", KANBAN_BOARD, "fields", json.dumps(CARD_FIELDS))
    return "обновлены: " + ", ".join(CARD_FIELDS)


def execute():
    setup_display_field()
    backfilled = backfill_categories_display()
    t = set_title_field()
    k = set_kanban_fields()
    frappe.clear_cache(doctype="Opportunity")
    frappe.db.commit()
    print("=== CRM: карточка канбана ===")
    print(f"Поле mw_categories_display создано; бэкфилл сделок: {backfilled}")
    print(f"title_field Opportunity → customer_name: {t}")
    print(f"Поля карточки канбана: {k}")
    print("Готово.")
