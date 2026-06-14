"""
CRM: карточка канбана сделок — осмысленные данные.

Было: заголовок = title (иногда email), поля = modified/owner/status/amount
(три из пяти бесполезны). Стало:
  - заголовок карточки = организация/клиент (customer_name, а не email в title);
  - поля карточки = Категория изделий, Объём (тонн), Сумма сделки, Дата касания.
  - убраны «Создано» (owner) и «Статус» (дублирует колонку канбана).

Идемпотентно. Запуск (bench console):
  import runpy; runpy.run_path('/tmp/crm_kanban.py')['execute']()
"""

import json
import frappe

KANBAN_BOARD = "Продажи"
# Категория (mw_product_categories) — Table MultiSelect; Frappe-канбан НЕ выводит
# значение child-таблицы на карточке (показывал пустой ярлык). Ограничение
# движка → на карточке не выводим. Заголовок = организация (customer_name),
# поля = объём + сумма + дата касания.
CARD_FIELDS = ["mw_estimated_volume", "opportunity_amount", "modified"]


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
    t = set_title_field()
    k = set_kanban_fields()
    frappe.clear_cache(doctype="Opportunity")
    frappe.db.commit()
    print("=== CRM: карточка канбана ===")
    print(f"title_field Opportunity → customer_name: {t}")
    print(f"Поля карточки канбана: {k}")
    print("Готово.")
