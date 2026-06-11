"""
Начальная настройка ERPNext: финансовый год и базовые настройки склада.
Запуск: bench --site erp.localhost execute erpnext.initial_setup.execute
Идемпотентен.
"""

import frappe


def create_fiscal_year():
    if frappe.db.exists("Fiscal Year", "2026"):
        return False

    companies = frappe.get_all("Company", pluck="name")
    doc = frappe.get_doc({
        "doctype":         "Fiscal Year",
        "year":            "2026",
        "year_start_date": "2026-01-01",
        "year_end_date":   "2026-12-31",
        "companies": [{"company": c} for c in companies],
    })
    doc.insert(ignore_permissions=True)
    return True


def execute():
    fiscal_year = create_fiscal_year()
    frappe.db.commit()

    frappe.db.set_single_value("Stock Settings", "allow_zero_valuation_rate", 1)
    frappe.db.commit()

    frappe.clear_cache()

    print(f"\n✅ Начальная настройка завершена:")
    print(f"   Финансовый год 2026: {'создан' if fiscal_year else 'уже существовал'}")
    print(f"   Allow Zero Valuation Rate: включён")
