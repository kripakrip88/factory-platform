"""
Мастер-скрипт настройки ERPNext — запускает все скрипты по порядку.
Если один упал — логирует ошибку и продолжает остальные.

Запуск: bench --site erp.localhost execute erpnext.setup_all.execute
"""

import traceback
import frappe

SCRIPTS = [
    ("initial_setup",     "Финансовый год + базовые настройки"),
    ("uom_setup",         "Единицы измерения, склады, группы, атрибуты"),
    ("crm_setup",         "Воронка CRM, скрытие лишних полей"),
    ("crm_product_categories", "Категории изделий + заводские поля лид/сделка"),
    ("crm_translations",  "Переводы диалога создания сделки"),
    ("nomenclature_setup","Номенклатура металлопроката"),
]


def execute():
    results = []

    for module_name, description in SCRIPTS:
        print(f"\n▶  {description} ({module_name})...")
        try:
            import importlib
            mod = importlib.import_module(f"erpnext.{module_name}")
            importlib.reload(mod)
            mod.execute()
            results.append((module_name, description, True, None))
            print(f"   ✅ OK")
        except Exception as e:
            err = traceback.format_exc()
            results.append((module_name, description, False, str(e)))
            print(f"   ❌ ОШИБКА: {e}")

    print("\n" + "=" * 60)
    print("СВОДКА")
    print("=" * 60)
    ok  = [r for r in results if r[2]]
    err = [r for r in results if not r[2]]
    for r in ok:
        print(f"  ✅  {r[1]}")
    for r in err:
        print(f"  ❌  {r[1]}: {r[3]}")
    print(f"\nИтого: {len(ok)} успешно, {len(err)} с ошибками")
