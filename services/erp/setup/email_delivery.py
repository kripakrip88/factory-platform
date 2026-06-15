"""
Починка приёма/отправки почты для Email Account mail.ru (идемпотентно).

Контекст (диагностика 2026-06-15): три проблемы доставки почты, причины:
  1) Приём не всех входящих: email_sync_option="UNSEEN" → письма, прочитанные в
     веб-почте mail.ru ДО pull (раз в 10 мин), Frappe пропускал навсегда.
     Фикс: "ALL" — тянуть по UID независимо от прочитанности.
  2) Исходящие не доходят: SMTP 550 "not local sender" — ERPNext слал от
     admin@example.com (email пользователя Administrator), mail.ru отвергал.
     Фикс: always_use_account_email_id_as_sender=1 → From = email аккаунта.
  3) Нет копии в «Отправленных» mail.ru: append_emails_to_sent_folder=0.
     Фикс: =1 + sent_folder_name="Sent" (IMAP APPEND в папку Sent ящика).

Пароль НЕ трогаем (авторизация проходит; вводит только Антон при необходимости).

Запуск: bench --site erp.localhost execute erpnext.email_delivery.execute
"""

import frappe

# Имя боевого ящика; если переименуют — поправить здесь или передать через переменную.
ACCOUNT = "PMK Park входящие (тест)"

DESIRED = {
    "email_sync_option": "ALL",                       # тянуть все письма, не только непрочитанные
    "always_use_account_email_id_as_sender": 1,        # From = email аккаунта (а не admin@example.com)
    "append_emails_to_sent_folder": 1,                 # копия отправленного в Sent ящика mail.ru
    "sent_folder_name": "Sent",
}


def execute(account: str = ACCOUNT):
    if not frappe.db.exists("Email Account", account):
        print(f"⚠️  Email Account «{account}» не найден — пропускаю (укажи верное имя).")
        return

    changed = {}
    for field, want in DESIRED.items():
        cur = frappe.db.get_value("Email Account", account, field)
        if str(cur) != str(want):
            frappe.db.set_value("Email Account", account, field, want)
            changed[field] = f"{cur} → {want}"
    frappe.db.commit()

    if changed:
        print(f"✓ Email Account «{account}» обновлён: {changed}")
    else:
        print(f"ℹ️  Email Account «{account}» уже настроен правильно.")
