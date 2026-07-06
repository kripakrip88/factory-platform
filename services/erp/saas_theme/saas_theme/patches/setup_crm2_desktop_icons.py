"""Desktop-грид (сетка приложений) строится из Desktop Icon, а НЕ из воркспейсов.

create_desktop_icons_from_workspace() создаёт иконки только для воркспейсов с `module`,
а CRM 2.0 — app-scoped (module-less) → пропущен. Поэтому заводим запись Desktop Icon
вручную. Плюс: скрываем App-плитку «Framework» (шум) и красим серый квадрат
«Калькуляторы» в синий (у него нет svg → fallback-квадрат по bg_color).

Иконка грида ищется по svg assets/<app>/icons/desktop_icons/<variant>/<scrub(label)>.svg
→ для «CRM 2.0» это saas_theme/.../crm_2.0.svg (лежит в public/icons/desktop_icons).
create_desktop_icons() только вставляет (не удаляет) и на migrate не зовётся →
запись переживёт будущие миграции. Идемпотентно.
"""

import frappe
from frappe.desk.doctype.desktop_icon.desktop_icon import clear_desktop_icons_cache


def execute():
    # 0. Workspace Sidebar «CRM 2.0» — КЛЮЧЕВОЕ: грид (get_sidebar_items, boot.py)
    #    строится из доктайпа `Workspace Sidebar`, а НЕ из `Workspace`. Для воркспейсов
    #    С модулем такая запись авто-создаётся (auto_generate_sidebar_from_module), а наш
    #    module-less CRM 2.0 её не получил → Desktop Icon отсеивался is_permitted (нет
    #    workspace_sidebar_item[label]). Создаём module-less (видна всем) с непустыми items.
    if not frappe.db.exists("Workspace Sidebar", "CRM 2.0"):
        frappe.get_doc({
            "doctype": "Workspace Sidebar",
            "title": "CRM 2.0",
            "header_icon": "users",
            "app": "saas_theme",
            "items": [
                {"type": "Link", "label": "Витрина", "link_type": "Page", "link_to": "crm2"},
                {"type": "Link", "label": "Сделки", "link_type": "DocType", "link_to": "Opportunity"},
                {"type": "Link", "label": "Лиды", "link_type": "DocType", "link_to": "Lead"},
            ],
        }).insert(ignore_permissions=True)

    # 1. CRM 2.0 в сетку приложений (app=saas_theme → svg-глиф crm_2.0.svg).
    #    Dynamic Link link_to капризничает на имени «CRM 2.0» (пробел+точка), хотя
    #    воркспейс существует → обходим валидацию ссылок (маршрут рабочий: иконка →
    #    воркспейс CRM 2.0 → редирект на страницу crm2, см. saas_theme.js).
    if not frappe.db.exists("Desktop Icon", {"label": "CRM 2.0", "icon_type": "Link"}):
        di = frappe.get_doc({
            "doctype": "Desktop Icon",
            "label": "CRM 2.0",
            "link_type": "Workspace Sidebar",
            "icon_type": "Link",
            "link_to": "CRM 2.0",
            "icon": "users",
            "app": "saas_theme",
            "bg_color": "blue",
            # standard=0 (кастомная, владелец Administrator → видна всем): migrate в
            # конце ПЕРЕСОБИРАЕТ standard=1 иконки и снёс бы нашу. standard=0 (как у
            # «Калькуляторов») переживает миграции.
            "standard": 0,
            "hidden": 0,
            "idx": 2,
        })
        di.flags.ignore_links = True
        di.insert(ignore_permissions=True, ignore_if_duplicate=True)

    # 2. Скрыть App-плитку «Framework» из грида (технический шум для менеджера).
    fw = frappe.db.exists("Desktop Icon", {"label": "Framework", "icon_type": "App"})
    if fw:
        frappe.db.set_value("Desktop Icon", fw, "hidden", 1)

    # 3. «Калькуляторы» — серый квадрат-заглушка (нет svg) → синий фон, ближе к семье.
    kalk = frappe.db.exists("Desktop Icon", {"label": "Калькуляторы"})
    if kalk:
        frappe.db.set_value("Desktop Icon", kalk, "bg_color", "blue")

    clear_desktop_icons_cache()
    frappe.db.commit()
