"""
Добавляет кнопку «Отмена» на формы новых документов.

Кнопка появляется только когда frm.is_new() === true и исчезает после сохранения.
Клик возвращает пользователя к списку соответствующего DocType.

Запуск:
    docker compose -f services/erp/docker-compose.yml cp \
      services/erp/setup/client_scripts/cancel_button.py backend:/tmp/cancel_button.py
    docker compose -f services/erp/docker-compose.yml exec backend \
      bench --site erp.localhost execute /tmp/cancel_button.py
"""

import frappe

SCRIPTS = [
    {
        "dt": "Lead",
        "name": "Lead — Cancel button on new",
        "script": """
frappe.ui.form.on('Lead', {
    refresh: function(frm) {
        if (frm.is_new()) {
            frm.add_custom_button(__('Отмена'), function() {
                frappe.set_route('List', 'Lead');
            }).addClass('btn-secondary');
        }
    }
});
""".strip(),
    },
    {
        "dt": "Opportunity",
        "name": "Opportunity — Cancel button on new",
        "script": """
frappe.ui.form.on('Opportunity', {
    refresh: function(frm) {
        if (frm.is_new()) {
            frm.add_custom_button(__('Отмена'), function() {
                frappe.set_route('List', 'Opportunity');
            }).addClass('btn-secondary');
        }
    }
});
""".strip(),
    },
]


def execute():
    for s in SCRIPTS:
        existing = frappe.db.get_value("Client Script", {"dt": s["dt"], "name": s["name"]})
        if existing:
            doc = frappe.get_doc("Client Script", existing)
            doc.script = s["script"]
            doc.enabled = 1
            doc.save(ignore_permissions=True)
            print(f"Updated: {s['name']}")
        else:
            doc = frappe.get_doc({
                "doctype": "Client Script",
                "name": s["name"],
                "dt": s["dt"],
                "view": "Form",
                "enabled": 1,
                "script": s["script"],
            })
            doc.insert(ignore_permissions=True)
            print(f"Created: {s['name']}")

    frappe.db.commit()
    print("Done — cancel buttons installed")


execute()
