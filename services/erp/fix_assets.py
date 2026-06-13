"""
Синхронизирует assets.json с реальными CSS/JS файлами на диске.

Проблема: assets.json хранится в Docker volume (erp_assets) и содержит
хэши бандлов. При каждом новом docker build хэши меняются (новые файлы
в image layer), но volume сохраняет старый assets.json → 404 на CSS.

Этот скрипт запускается при старте backend контейнера и обновляет
assets.json так чтобы хэши совпадали с файлами реально лежащими на диске.
"""
import json
import os
import re

ASSETS_JSON = "/home/frappe/frappe-bench/assets/assets.json"
ASSETS_DIR = "/home/frappe/frappe-bench/assets"
APPS = ["frappe", "erpnext", "hrms", "payments", "crm"]


def scan_actual_files():
    """Сканирует реальные bundle файлы на диске и возвращает маппинг."""
    actual = {}
    for app in APPS:
        for ext in ["css", "js"]:
            dist_dir = os.path.join(ASSETS_DIR, app, "dist", ext)
            # Разворачиваем симлинки
            real_dir = os.path.realpath(dist_dir) if os.path.exists(dist_dir) else None
            if not real_dir or not os.path.isdir(real_dir):
                continue
            for fname in os.listdir(real_dir):
                if fname.endswith(".map"):
                    continue
                m = re.match(r"^(.+\.bundle)\.[A-Z0-9]+\." + ext + r"$", fname)
                if m:
                    bundle_key = m.group(1) + "." + ext
                    actual[bundle_key] = f"/assets/{app}/dist/{ext}/{fname}"
    return actual


def fix_assets_json():
    if not os.path.exists(ASSETS_JSON):
        print("fix_assets: assets.json not found, skipping")
        return

    with open(ASSETS_JSON) as f:
        data = json.load(f)

    actual = scan_actual_files()
    changed = 0

    for key, real_path in actual.items():
        if key in data and data[key] != real_path:
            print(f"fix_assets: {key}: {data[key]} -> {real_path}")
            data[key] = real_path
            changed += 1

    if changed:
        with open(ASSETS_JSON, "w") as f:
            json.dump(data, f, indent=2)
        print(f"fix_assets: updated {changed} entries in assets.json")
    else:
        print("fix_assets: assets.json is up to date")


if __name__ == "__main__":
    fix_assets_json()
