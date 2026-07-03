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
SHARED_MAILBOX = "PMK Park входящие (тест)"   # общий ящик отдела продаж
USER_LANG = "ru"

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

# Технические/неиспользуемые справочники со стандартным read=All (виден каждому
# юзеру по прямому URL, напр. /app/salutation). Менеджеру не нужны — снимаем read
# у роли All (System Manager/Administrator доступ сохраняют).
# NB: "Module Def" НЕ включён — его read выдаётся на уровне фреймворка (core-метаданные
# десктопа), Custom DocPerm его не ограничивает, а перезапись core-доктайпа рискованна.
LOCK_FROM_ALL = [
    "Salutation", "Gender", "Connected App",
    "Token Cache", "Video", "Voice Call Settings", "Personal Data Download Request",
]
# Salutation/Gender — Link-поля на Контакте: прячем, чтобы пустая выпадашка не мешала.
HIDE_ON_CONTACT = ["salutation", "gender"]


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


def _add_has_role(parent, role, parenttype="Workspace"):
    """Прямая SQL-вставка строки Has Role. Через ORM нельзя: Has Role.before_insert
    проверяет дубли по parent+role БЕЗ учёта parenttype → ложно падает, если такой
    parent+role уже есть у другого типа (напр. одноимённый Workspace)."""
    if frappe.db.exists("Has Role", {"parenttype": parenttype, "parent": parent,
                                     "parentfield": "roles", "role": role}):
        return
    frappe.db.sql(
        """INSERT INTO `tabHas Role`
           (name, parent, parenttype, parentfield, role, creation, modified, owner, modified_by)
           VALUES (%s, %s, %s, 'roles', %s, now(), now(), 'Administrator', 'Administrator')""",
        (frappe.generate_hash(length=12), parent, parenttype, role))


def gate_desktop_icons():
    """Верхнее меню темы (saas_theme.js) строится из frappe.boot.desktop_icons, а их
    видимость решает Desktop Icon.is_permitted → роли на самой ИКОНКЕ (не на воркспейсе).
    Поэтому нежелательные модули (напр. Selling — не скрыт, т.к. Customer в его модуле)
    гейтим ролью на Desktop Icon. CRM/Калькуляторы оставляем открытыми."""
    icons = frappe.get_all("Desktop Icon",
                           filters={"link_type": "Workspace Sidebar"},
                           fields=["name", "label", "hidden"])
    for ic in icons:
        if ic.label in ALLOWED_WORKSPACES:
            continue
        roles_now = set(frappe.get_all(
            "Has Role", filters={"parenttype": "Desktop Icon", "parent": ic.name}, pluck="role"))
        if not roles_now:
            _add_has_role(ic.name, GATE_ROLE, parenttype="Desktop Icon")
            print(f"  ✓ иконка меню {ic.label}: гейт {GATE_ROLE} (скрыта от менеджера)")
        else:
            print(f"  = иконка меню {ic.label}: уже ограничена ({roles_now})")
    frappe.db.commit()
    frappe.clear_cache()  # сбросить кэш desktop_icons, чтобы гейт подхватился


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
    # язык = ru → применяются кастомные переводы (сборник в Translation DocType под кодом ru)
    u.language = USER_LANG
    # общий ящик отдела продаж → вкладка «Электронная почта» (иначе ошибка inbox)
    _link_mailbox(u)
    u.save(ignore_permissions=True)
    # подстраховка: убедиться, что НЕТ привилегированных ролей
    forbidden = {"System Manager", "Accounts Manager", "Accounts User", "Stock Manager",
                 "Stock User", "Manufacturing Manager", "Manufacturing User", "Purchase Manager"}
    has_forbidden = forbidden & {r.role for r in frappe.get_doc("User", email).roles}
    frappe.db.commit()
    return {"user": email, "created": created, "language": USER_LANG,
            "roles": [r.role for r in frappe.get_doc("User", email).roles],
            "forbidden_present": list(has_forbidden)}


def _link_mailbox(user_doc):
    """Привязать общий ящик к User Email (если есть аккаунт и ещё не привязан)."""
    if not frappe.db.exists("Email Account", SHARED_MAILBOX):
        return False
    have = {r.email_account for r in (user_doc.user_emails or [])}
    if SHARED_MAILBOX not in have:
        user_doc.append("user_emails", {"email_account": SHARED_MAILBOX})
        return True
    return False


@frappe.whitelist()
def fix_manager_account(email):
    """Доустановить существующему менеджеру: язык ru + привязка общего ящика + сброс кэша."""
    u = frappe.get_doc("User", email)
    u.language = USER_LANG
    linked = _link_mailbox(u)
    u.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(user=email)
    return {"user": email, "language": USER_LANG, "mailbox_linked": linked,
            "mailboxes": [r.email_account for r in frappe.get_doc("User", email).user_emails]}


@frappe.whitelist()
def reset_link(email):
    """Свежая прямая ссылка задания пароля (без почты) — отдать админу.
    Очищает старый ключ/new_password, ставит новый ключ, строит /update-password URL."""
    from frappe.utils import now_datetime, get_url
    from frappe.utils.data import sha256_hash
    # Frappe хранит SHA256-хеш ключа (user.py), в URL — плейн-текст. Иначе update_password = 410.
    key = frappe.generate_hash()
    frappe.db.set_value("User", email, {
        "reset_password_key": sha256_hash(key),
        "last_reset_password_key_generated_on": now_datetime(),
        "new_password": None,
        "enabled": 1,
    }, update_modified=False)
    frappe.db.commit()
    return {"user": email, "url": get_url(f"/update-password?key={key}")}


@frappe.whitelist()
def boot_nav(user):
    """Диагностика верхнего меню темы: что в desktop_icons (Workspace Sidebar) и
    workspace_sidebar_item под пользователем (ровно то, что фильтрует saas_theme.js)."""
    frappe.set_user(user)
    try:
        from frappe.boot import get_bootinfo
        b = get_bootinfo()
        di = b.get("desktop_icons") or []
        icons = [{"label": i.get("label"), "hidden": i.get("hidden")}
                 for i in di if i.get("link_type") == "Workspace Sidebar"]
        wsi = b.get("workspace_sidebar_item") or {}
        return {"sidebar_icons": icons, "wsi_keys": sorted(wsi.keys())}
    finally:
        frappe.set_user("Administrator")


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


def restrict_internal_doctypes():
    """Снять read у роли All на технических справочниках (LOCK_FROM_ALL), чтобы
    не-админ не открывал их по прямому URL. Механизм: Custom DocPerm перекрывает
    стандартные права — копируем их (setup_custom_perms) и удаляем строку роли All.
    Плюс прячем salutation/gender на Контакте. Идемпотентно."""
    from frappe.permissions import setup_custom_perms
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    for dt in LOCK_FROM_ALL:
        if not frappe.db.exists("DocType", dt):
            print(f"  ⚠ нет доктайпа: {dt}")
            continue
        setup_custom_perms(dt)  # копирует стандартные DocPerm в Custom DocPerm (если ещё нет)
        if frappe.db.count("Custom DocPerm", {"parent": dt, "role": "All"}):
            frappe.db.delete("Custom DocPerm", {"parent": dt, "role": "All"})
            print(f"  ✓ {dt}: снят read у роли All")
        else:
            print(f"  = {dt}: у роли All прав уже нет")
        frappe.clear_cache(doctype=dt)

    contact_meta = frappe.get_meta("Contact")
    for fn in HIDE_ON_CONTACT:
        if contact_meta.get_field(fn):
            make_property_setter("Contact", fn, "hidden", 1, "Check",
                                 validate_fields_for_doctype=False)
            print(f"  ✓ Contact.{fn}: скрыт")
    frappe.db.commit()


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
    print("— гейт иконок верхнего меню темы (Desktop Icon) —")
    gate_desktop_icons()
    print("— ограничение технических справочников (read=All → только админ) —")
    restrict_internal_doctypes()
    frappe.db.commit()
    frappe.clear_cache()  # без сброса кэша новые roles воркспейсов не подхватятся
    print("=== Готово ===")
    return {"role": ROLE, "write_doctypes": WRITE_DOCTYPES, "read_doctypes": READ_DOCTYPES}
