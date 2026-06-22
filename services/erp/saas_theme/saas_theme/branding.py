# -*- coding: utf-8 -*-
"""Брендинг «ПМК Парк» штатными средствами ERPNext (воспроизводимо, переживает редеплой).

Ставит название и логотип на странице входа, в шапке (navbar), вкладке браузера и favicon
через Website Settings + Navbar Settings (данные в БД, не хаки в ядре).

Логотип кладётся в репо (public/images/) → скрипт заливает его как File и проставляет ссылки,
поэтому брендинг воспроизводится на обеих средах одной командой:
  bench --site erp.localhost execute saas_theme.branding.execute

Если файлов лого нет — ставится только текстовый брендинг (название), лого добавится позже.
"""

import os
import frappe

APP_NAME = "ПМК Парк"
TITLE_PREFIX = "ПМК Парк"

# Файлы логотипа в приложении saas_theme (public/images). Достаточно одного (LOGO);
# FAVICON опционален — если нет, используем LOGO.
_IMG_DIR = os.path.join(os.path.dirname(__file__), "public", "images")
LOGO_FILE = "pmk-logo.png"        # лого на вход + navbar
FAVICON_FILE = "pmk-favicon.png"  # иконка вкладки (если нет — берём LOGO)


def _upload(filename):
    """Залить картинку из public/images как публичный File, вернуть file_url. None если нет файла."""
    path = os.path.join(_IMG_DIR, filename)
    if not os.path.exists(path):
        return None
    # идемпотентность: если File с таким именем уже есть — переиспользуем
    existing = frappe.get_all("File", filters={"file_name": filename, "is_private": 0},
                              fields=["file_url"], limit=1)
    if existing:
        return existing[0].file_url
    with open(path, "rb") as f:
        content = f.read()
    fdoc = frappe.get_doc({
        "doctype": "File", "file_name": filename, "is_private": 0,
        "content": content,
    }).insert(ignore_permissions=True)
    return fdoc.file_url


def execute():
    print(f"=== Брендинг «{APP_NAME}» ===")
    logo_url = _upload(LOGO_FILE)
    favicon_url = _upload(FAVICON_FILE) or logo_url
    print(f"  logo: {logo_url or '— (нет файла, только текст)'}")
    print(f"  favicon: {favicon_url or '—'}")

    # --- Website Settings (вход, вкладка, favicon) ---
    ws = frappe.get_single("Website Settings")
    ws.app_name = APP_NAME
    ws.title_prefix = TITLE_PREFIX
    # текстовый бренд для website-навбара (тема тёмная, без новых цветов)
    ws.brand_html = f'<span style="font-weight:600">{APP_NAME}</span>'
    if logo_url:
        ws.app_logo = logo_url          # логотип на странице входа
        ws.banner_image = logo_url      # бренд-картинка
    if favicon_url:
        ws.favicon = favicon_url
    ws.flags.ignore_mandatory = True
    ws.save(ignore_permissions=True)
    print("  ✓ Website Settings обновлён")

    # --- Navbar Settings (логотип в шапке desk) ---
    if logo_url:
        nb = frappe.get_single("Navbar Settings")
        nb.app_logo = logo_url
        nb.flags.ignore_mandatory = True
        nb.save(ignore_permissions=True)
        print("  ✓ Navbar Settings: лого в шапке")

    # --- System Settings: имя приложения для вкладки (если поле есть) ---
    # frappe.boot.app_name = Website Settings.app_name → вкладка/вход показывают «ПМК Парк».

    frappe.db.commit()
    frappe.clear_cache()
    print("=== Готово (нужен hard-reload/инкогнито, чтобы увидеть вход) ===")
    return {"app_name": APP_NAME, "logo": logo_url, "favicon": favicon_url}
