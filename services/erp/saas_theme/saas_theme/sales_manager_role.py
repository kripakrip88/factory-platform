# -*- coding: utf-8 -*-
"""Роль «Менеджер по продажам» + права (воспроизводимо staging→prod).

Менеджеры по продажам:
  - видят и редактируют документы ДРУГ ДРУГА (read+create+write на ВСЕ записи,
    if_owner НЕ ставим);
  - НЕ удаляют (delete=0 везде);
  - видят CRM (Лид, Сделка, Покупатель, Почта, Контакты, Адреса) + Калькуляторы;
  - НЕ видят Производство/Закупки/Запасы/Настройки/бухгалтерию (нет роли с доступом
    + воркспейсы ограничены ролями — см. restrict_workspaces()).
  - История изменений (track_changes) включается на CRM-доктайпах.

Запуск:
  bench --site erp.localhost execute saas_theme.sales_manager_role.execute
  
Идемпотентно: повторный прогон не плодит дубли.

⚠️ Пользователя НЕ создаёт и пароли НЕ трогает — это отдельный шаг (create_user),
   активация через приглашение/смену пароля в UI.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

ROLE = "Менеджер по продажам"

# read + create + write (delete=0, if_owner=0) — работа с записями всех менеджеров
WRITE_DOCTYPES = [
    # CRM
    "Lead", "Opportunity", "Customer", "Communication", "Contact", "Address",
    # Калькуляторы — заведение расчётов
    "Dobor Order", "Dobor Profile", "Cutting Plan", "Metal Spec",
]

# только чтение — справочники проката/веса (менеджер не портит сортамент)
READ_DOCTYPES = [
    "Metal Profile", "Steel Grade", "Metal Sheet Grade", "Stock Length", "Dobor Coating",
]

# Frappe Pages калькуляторов — доступ роли
PAGES = ["metal_calculator", "dobor_builder"]

# История изменений
TRACK_CHANGES = ["Lead", "Opportunity", "Customer", "Communication"]

# Воркспейсы, которые менеджер ДОЛЖЕН видеть (остальные public-воркспейсы прячем)
ALLOWED_WORKSPACES = ["CRM", "Калькуляторы"]
# Роль-гейт для скрытых воркспейсов: их увидят только эти роли (не менеджер).
GATE_ROLE = "System Manager"


def ensure_role():
    if not frappe.db.exists("Role", ROLE):
        doc = frappe.new_doc("Role")
        doc.role_name = ROLE
        doc.desk_access = 1
        doc.insert(ignore_permissions=True)
    else:
        frappe.db.set_value("Role", ROLE, "desk_access", 1)


def _grant(doctype, create, write):
    """Идемпотентно: добавить право роли на доктайп с нужными флагами."""
    if not frappe.db.exists("DocType", doctype):
        print(f"  ⚠ пропуск (нет доктайпа): {doctype}")
        return
    # add_permission создаёт строку прав (read=1 по умолчанию), если её нет
    add_permission(doctype, ROLE, 0)
    props = {"read": 1, "create": int(create), "write": int(write),
             "delete": 0, "if_owner": 0, "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}
    for ptype, val in props.items():
        update_permission_property(doctype, ROLE, 0, ptype, val, validate=False)
    print(f"  ✓ {doctype}: read=1 create={int(create)} write={int(write)} delete=0")


def grant_permissions():
    for dt in WRITE_DOCTYPES:
        _grant(dt, create=1, write=1)
    for dt in READ_DOCTYPES:
        _grant(dt, create=0, write=0)


def grant_pages():
    for pg in PAGES:
        if not frappe.db.exists("Page", pg):
            print(f"  ⚠ нет страницы: {pg}")
            continue
        doc = frappe.get_doc("Page", pg)
        have = {r.role for r in (doc.roles or [])}
        if ROLE not in have:
            doc.append("roles", {"role": ROLE})
            doc.save(ignore_permissions=True)
            print(f"  ✓ страница {pg}: добавлена роль")
        else:
            print(f"  = страница {pg}: роль уже есть")


def enable_track_changes():
    for dt in TRACK_CHANGES:
        if frappe.db.exists("DocType", dt):
            if not frappe.db.get_value("DocType", dt, "track_changes"):
                frappe.db.set_value("DocType", dt, "track_changes", 1)
                print(f"  ✓ track_changes вкл: {dt}")
            else:
                print(f"  = track_changes уже вкл: {dt}")


def restrict_workspaces():
    """Менеджер видит только ALLOWED_WORKSPACES.
    Механизм Frappe: воркспейс с заданной roles-таблицей виден только этим ролям;
    без roles — виден всем. Поэтому:
      - на скрытые public-воркспейсы вешаем GATE_ROLE (их увидят только System Manager и т.п.);
      - на разрешённые добавляем роль менеджера (+ GATE_ROLE, чтобы админ тоже видел).
    """
    # Стандартные воркспейсы содержат «хрупкие» дочерние Shortcut (mandatory `type`,
    # теряется при .save() через API — баг Frappe). Поэтому правим roles-таблицу
    # НАПРЯМУЮ в БД (tabHas Role), без полной валидации документа.
    all_ws = frappe.get_all("Workspace", filters={"public": 1}, fields=["name"])
    for w in all_ws:
        roles_now = set(frappe.get_all(
            "Has Role", filters={"parenttype": "Workspace", "parent": w.name}, pluck="role"))
        if w.name in ALLOWED_WORKSPACES:
            for r in ({ROLE, GATE_ROLE} - roles_now):
                _add_has_role(w.name, r)
                print(f"  ✓ воркспейс {w.name}: +{r} (виден менеджеру)")
        else:
            if ROLE in roles_now:
                frappe.db.delete("Has Role", {"parenttype": "Workspace", "parent": w.name, "role": ROLE})
                print(f"  ✓ воркспейс {w.name}: убрана роль менеджера")
            if not (roles_now - {ROLE}):
                _add_has_role(w.name, GATE_ROLE)
                print(f"  ✓ воркспейс {w.name}: гейт {GATE_ROLE} (скрыт от менеджера)")
            else:
                print(f"  = воркспейс {w.name}: уже ограничен ({roles_now})")
    frappe.db.commit()


def _add_has_role(workspace, role):
    """Прямая вставка строки Has Role для воркспейса (в обход хрупкой валидации Shortcut)."""
    if frappe.db.exists("Has Role", {"parenttype": "Workspace", "parent": workspace,
                                     "parentfield": "roles", "role": role}):
        return
    frappe.get_doc({
        "doctype": "Has Role", "parenttype": "Workspace", "parent": workspace,
        "parentfield": "roles", "role": role,
    }).insert(ignore_permissions=True)


@frappe.whitelist()
def create_user(email, first_name="Менеджер", last_name="", send_welcome=1):
    """Завести пользователя ТОЛЬКО с ролью менеджера. Пароль НЕ задаём:
    активация через welcome-email со ссылкой задания пароля (send_welcome=1).
    На staging вызывать с send_welcome=0 (почты нет)."""
    if frappe.db.exists("User", email):
        u = frappe.get_doc("User", email)
        created = False
    else:
        u = frappe.new_doc("User")
        u.email = email
        u.first_name = first_name
        u.last_name = last_name
        u.send_welcome_email = int(send_welcome)
        u.insert(ignore_permissions=True)
        created = True
    if ROLE not in {r.role for r in u.roles}:
        u.add_roles(ROLE)
    # подстраховка: убедиться, что НЕТ привилегированных ролей
    forbidden = {"System Manager", "Accounts Manager", "Accounts User", "Stock Manager",
                 "Stock User", "Manufacturing Manager", "Manufacturing User", "Purchase Manager"}
    has_forbidden = forbidden & {r.role for r in frappe.get_doc("User", email).roles}
    frappe.db.commit()
    return {"user": email, "created": created, "roles": [r.role for r in frappe.get_doc("User", email).roles],
            "forbidden_present": list(has_forbidden)}


@frappe.whitelist()
def check_access(user):
    """Проверка ПОД пользователем (set_user): роли, права (delete должен быть 0),
    видимые воркспейсы. Тестирует движок прав без логина/пароля."""
    out = {"user": user}
    frappe.set_user(user)
    try:
        out["roles"] = frappe.get_roles(user)
        perm = {}
        for dt in ["Lead", "Opportunity", "Customer", "Communication", "Metal Spec", "Dobor Order"]:
            perm[dt] = {
                "read": frappe.has_permission(dt, "read"),
                "create": frappe.has_permission(dt, "create"),
                "write": frappe.has_permission(dt, "write"),
                "delete": frappe.has_permission(dt, "delete"),
            }
        # запрещённые модули
        for dt in ["Purchase Order", "Stock Entry", "Work Order", "Sales Invoice", "Payment Entry"]:
            if frappe.db.exists("DocType", dt):
                perm[dt] = {"read": frappe.has_permission(dt, "read")}
        out["perm"] = perm
        from frappe.desk.desktop import get_workspace_sidebar_items
        ws = get_workspace_sidebar_items().get("pages", [])
        out["workspaces"] = sorted({w.get("title") or w.get("name") for w in ws})
    finally:
        frappe.set_user("Administrator")
    return out


def execute():
    print(f"=== Роль «{ROLE}» ===")
    ensure_role()
    print("— права на доктайпы —")
    grant_permissions()
    print("— страницы калькуляторов —")
    grant_pages()
    print("— track_changes —")
    enable_track_changes()
    print("— видимость воркспейсов (менеджер видит только CRM + Калькуляторы) —")
    restrict_workspaces()
    frappe.db.commit()
    frappe.clear_cache()  # без сброса кэша новые roles воркспейсов не подхватятся
    print("=== Готово ===")
    return {"role": ROLE, "write_doctypes": WRITE_DOCTYPES, "read_doctypes": READ_DOCTYPES}
