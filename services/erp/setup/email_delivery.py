"""
Починка приёма/отправки почты Email Account mail.ru (идемпотентно).

Контекст:
  1) Приём не всех входящих: email_sync_option="UNSEEN" → прочитанные в веб-почте
     письма Frappe пропускал. Фикс: "ALL".
  2) Исходящие не доходят: SMTP 550 "not local sender". Фикс:
     always_use_account_email_id_as_sender=1 → From = email аккаунта.
  3) Копия в «Отправленных»: append_emails_to_sent_folder=1.
     ⚠️ Имя папки на mail.ru — «Отправленные» (спец-флаг \Sent), НЕ "Sent".
     Раньше стояло "Sent" — append шёл в несуществующую папку.
  4) ОТПРАВЛЕННЫЕ С ДРУГИХ УСТРОЙСТВ не подтягивались: синхронизировался только
     INBOX. Фикс: добавляем IMAP Folder «Отправленные» (pull) — письма,
     отправленные с веб/телефона, появляются в ERPNext как sent_or_received=Sent.
     Дубли отсекаются Frappe по Message-ID (письма, отправленные самим ERPNext,
     уже имеют Communication).

Пароль НЕ трогаем (вводит Антон). Имя папки выверено по IMAP LIST mail.ru.

Запуск: bench --site erp.localhost execute metal_calculator... нет —
        bench --site erp.localhost execute setup.email_delivery.execute
(или скопировать функцию в bench console).
"""

import frappe

ACCOUNT = "PMK Park входящие (тест)"
SENT_FOLDER = "Отправленные"  # реальное имя папки \Sent на mail.ru (выверено IMAP LIST)

DESIRED = {
	"email_sync_option": "ALL",
	"always_use_account_email_id_as_sender": 1,
	"append_emails_to_sent_folder": 1,
	"sent_folder_name": SENT_FOLDER,
}


def execute(account: str = ACCOUNT, sent_folder: str = SENT_FOLDER):
	if not frappe.db.exists("Email Account", account):
		print(f"⚠️  Email Account «{account}» не найден — пропускаю.")
		return

	doc = frappe.get_doc("Email Account", account)
	changed = {}

	# 1-3: поля приёма/отправки/копии в Sent
	for field, want in DESIRED.items():
		if field == "sent_folder_name":
			want = sent_folder
		cur = doc.get(field)
		if str(cur) != str(want):
			doc.set(field, want)
			changed[field] = f"{cur} → {want}"

	# 4: pull-синхронизация папки «Отправленные» (зеркало строки INBOX: append_to=None)
	folders = {f.folder_name for f in (doc.imap_folder or [])}
	if "INBOX" not in folders:
		# на всякий случай не теряем INBOX
		doc.append("imap_folder", {"folder_name": "INBOX", "append_to": None})
		changed["imap_folder"] = "+INBOX"
	if sent_folder not in folders:
		doc.append("imap_folder", {"folder_name": sent_folder, "append_to": None})
		changed["imap_folder_sent"] = f"+{sent_folder}"

	if changed:
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		print(f"✓ Email Account «{account}» обновлён: {changed}")
	else:
		print(f"ℹ️  Email Account «{account}» уже настроен правильно.")
