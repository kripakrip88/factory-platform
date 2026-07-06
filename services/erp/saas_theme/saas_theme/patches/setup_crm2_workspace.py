"""CRM 2.0 — раздел в лаунчере + скрытие технического «Build» (Framework).

Воркспейс делаем APP-scoped (поле `app`, БЕЗ `module`) — иначе миграция снесёт его
как орфан (грабли Frappe v16, см. metal_calculator/install.py и память
project_metal_calc_workspace). Клик по воркспейсу редиректится на страницу-витрину
`crm2` (см. saas_theme.js, router.on change). Идемпотентно (delete+recreate).
"""

import json

import frappe

WS = "CRM 2.0"


def execute():
    if frappe.db.exists("Workspace", WS):
        frappe.delete_doc("Workspace", WS, force=True, ignore_permissions=True)

    frappe.get_doc({
        "doctype": "Workspace",
        "name": WS,
        "label": WS,
        "title": WS,
        "app": "saas_theme",
        "public": 1,
        "is_hidden": 0,
        "icon": "users",
        "indicator_color": "blue",
        "sequence_id": 15.0,
        "content": json.dumps([
            {"id": "hdr_crm2", "type": "header", "data": {"text": "<span class=\"h4\"><b>CRM 2.0</b></span>", "col": 12}},
            {"id": "sc_crm2", "type": "shortcut", "data": {"shortcut_name": "Открыть CRM 2.0", "col": 4}},
        ]),
        "links": [],
        "shortcuts": [
            {"type": "Page", "label": "Открыть CRM 2.0", "link_to": "crm2", "color": "Blue", "doc_view": ""},
        ],
    }).insert(ignore_permissions=True)

    # Скрыть технический воркспейс «Build» (Framework) из лаунчера — шум для менеджера.
    if frappe.db.exists("Workspace", "Build"):
        frappe.db.set_value("Workspace", "Build", "is_hidden", 1)

    frappe.db.commit()
