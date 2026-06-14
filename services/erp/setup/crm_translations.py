"""
CRM, часть 2/3: добить перевод диалога создания сделки (лид → сделка).

В диалоге «Создать Коммерческую сделку» часть строк оставалась по-английски.
Добавляем переводы в Translation DocType (как остальные переводы проекта).
Идемпотентно: existing по (language, source_text) обновляется, иначе создаётся.

Запуск:
    docker cp services/erp/setup/crm_translations.py erp-backend-1:/tmp/x.py
    docker exec erp-backend-1 bash -c "cd /home/frappe/frappe-bench && \
      bench --site erp.localhost console" <<'PY'
    import runpy; runpy.run_path('/tmp/x.py')['execute']()
    PY
"""

import frappe

LANG = "ru"

TRANSLATIONS = {
    # Диалог создания сделки из лида
    "Prospect Name": "Наименование потенциального клиента",
    "Create Contact": "Создать контактное лицо",
    # Лик английского имени кастомного доктайпа из части 1 («Создать новую …»)
    "MW Product Category": "Категория изделий",
}


def execute():
    created, updated = 0, 0
    for source, translated in TRANSLATIONS.items():
        existing = frappe.get_all(
            "Translation",
            filters={"language": LANG, "source_text": source},
            pluck="name",
            limit=1,
        )
        if existing:
            frappe.db.set_value("Translation", existing[0], "translated_text", translated)
            updated += 1
        else:
            frappe.get_doc({
                "doctype": "Translation",
                "language": LANG,
                "source_text": source,
                "translated_text": translated,
            }).insert(ignore_permissions=True)
            created += 1
    frappe.db.commit()
    frappe.clear_cache()

    print("=== CRM: переводы диалога создания сделки ===")
    print(f"Переводов создано: {created}, обновлено: {updated}")
    print("Готово.")
