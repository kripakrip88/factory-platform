# -*- coding: utf-8 -*-
"""Почта mail.ru: фикс приёма/отправки + восстановление ИМЁН отправителей.

Контекст: frappe.utils.parse_addr на заголовке вида
  =?utf-8?B?...?= <kev.unit@mail.ru>
теряет display-name и возвращает САМ email как имя → sender_full_name = email.
decode_email при этом отрабатывает правильно. Ядро Frappe НЕ патчим — вместо
этого сверяем имена из IMAP правильным парсером (email.utils.parseaddr поверх
декодированного заголовка) и проставляем sender_full_name.

- fix_email_account: настройка Email Account (sync ALL, From=аккаунт, копия в
  «Отправленные», + IMAP Folder «Отправленные» для приёма отправленных).
- reconcile_sender_names: бэкфилл + go-forward (планировщик) — обновляет
  sender_full_name там, где он пуст или равен email, по заголовку From с сервера.

Запуск вручную:
  bench --site erp.localhost execute saas_theme.email_names.fix_email_account
  bench --site erp.localhost execute saas_theme.email_names.reconcile_sender_names
"""

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.utils import parseaddr

import frappe

ACCOUNT = "PMK Park входящие (тест)"


def _imap_connect(acc):
	M = imaplib.IMAP4_SSL(acc.email_server or "imap.mail.ru", 993)
	M.login(acc.email_id, acc.get_password("password"))
	return M


def find_sent_folder(acc):
	"""Имя папки \\Sent в IMAP-кодировке (modified UTF-7, ascii) — берём с сервера.
	НЕЛЬЗЯ хардкодить «Отправленные» (Unicode): imaplib шлёт имя как ASCII → падает."""
	try:
		M = _imap_connect(acc)
		typ, data = M.list()
		M.logout()
		for d in data:
			line = d.decode("utf-8", "replace") if isinstance(d, bytes) else str(d)
			if "\\Sent" in line:
				q = re.findall(r'"([^"]*)"', line)
				if q:
					return q[-1]
	except Exception as e:
		frappe.log_error(f"find_sent_folder: {e}", "email_names")
	return None


# ---------------- Задача 1: настройка Email Account ----------------

@frappe.whitelist()
def fix_email_account(account: str = ACCOUNT):
	"""Идемпотентно: приём всех писем, отправка от аккаунта, копия и приём «Отправленных»."""
	if not frappe.db.exists("Email Account", account):
		return f"Email Account «{account}» не найден"
	doc = frappe.get_doc("Email Account", account)
	sent_folder = find_sent_folder(doc)
	if not sent_folder:
		return "Не нашёл папку \\Sent на сервере — пропускаю настройку Sent"
	desired = {
		"email_sync_option": "ALL",
		"always_use_account_email_id_as_sender": 1,
		"append_emails_to_sent_folder": 1,
		"sent_folder_name": sent_folder,
	}
	changed = {}
	for field, want in desired.items():
		if str(doc.get(field)) != str(want):
			doc.set(field, want)
			changed[field] = want
	folders = {f.folder_name for f in (doc.imap_folder or [])}
	if "INBOX" not in folders:
		doc.append("imap_folder", {"folder_name": "INBOX", "append_to": None})
		changed["+INBOX"] = 1
	if sent_folder not in folders:
		doc.append("imap_folder", {"folder_name": sent_folder, "append_to": None})
		changed["+sent"] = sent_folder
	if changed:
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	return {"account": account, "changed": changed}


# ---------------- Задача 2: имена отправителей из From ----------------

def _decode_from_name(raw_from):
	"""Корректное имя из заголовка From (RFC2047 + parseaddr). None если имени нет."""
	if not raw_from:
		return None
	try:
		dec = str(make_header(decode_header(raw_from)))
	except Exception:
		dec = raw_from
	name = (parseaddr(dec)[0] or "").strip()
	if name and "@" not in name:
		return name
	return None


def _mid(s):
	return (s or "").strip().strip("<>").strip()


def _imap_name_map(acc, folders, per_folder=1000):
	"""Карта Message-ID → реальное имя из заголовков From по папкам IMAP."""
	out = {}
	try:
		M = imaplib.IMAP4_SSL(acc.email_server or "imap.mail.ru", 993)
		M.login(acc.email_id, acc.get_password("password"))
	except Exception as e:
		frappe.log_error(f"IMAP login: {e}", "email_names")
		return out
	for folder in folders:
		try:
			typ, _ = M.select(folder, readonly=True)
			if typ != "OK":
				continue
			typ, data = M.search(None, "ALL")
			ids = (data[0].split() if data and data[0] else [])[-per_folder:]
			if not ids:
				continue
			typ, msgs = M.fetch(b",".join(ids), "(BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)])")
			for part in msgs:
				if not isinstance(part, tuple):
					continue
				msg = email.message_from_string(part[1].decode("utf-8", "replace"))
				mid = _mid(msg.get("Message-ID"))
				nm = _decode_from_name(msg.get("From"))
				if mid and nm:
					out[mid] = nm
		except Exception as e:
			frappe.log_error(f"IMAP {folder}: {e}", "email_names")
	try:
		M.logout()
	except Exception:
		pass
	return out


# ---------------- Задача 1/2/3: направление писем (Sent vs Received) ----------------

def _account_emails():
	"""Наши собственные адреса (email_id входящих ящиков), lower-case."""
	vals = frappe.get_all("Email Account", filters={"enable_incoming": 1}, pluck="email_id")
	return {v.lower() for v in vals if v}


def fix_direction(doc, method=None):
	"""Go-forward (before_insert): письмо от НАШЕГО ящика = Sent (а не Received).
	Письма из папки «Отправленные» mail.ru имеют From=наш адрес → раньше падали как
	Received и смешивались с входящими. Признак «sender = наш ящик» надёжен:
	у настоящих входящих From чужой (клиент)."""
	if (getattr(doc, "communication_medium", "") or "").lower() != "email":
		return
	sender = (getattr(doc, "sender", "") or "").strip().lower()
	if sender and sender in _account_emails() and doc.sent_or_received != "Sent":
		doc.sent_or_received = "Sent"


@frappe.whitelist()
def backfill_sent_direction(apply=0):
	"""Бэкфилл (Задача 2): наши отправленные, помеченные Received, перемечаем в Sent.
	Критерий — sender = наш ящик (НЕ трогает реальные входящие, у них From чужой).
	apply=0 — только посчитать; apply=1 — применить."""
	emails = _account_emails()
	if not emails:
		return {"error": "нет email-аккаунтов с приёмом"}
	ph = ", ".join(["%s"] * len(emails))
	params = list(emails)
	cnt = frappe.db.sql(
		f"""SELECT count(*) FROM `tabCommunication`
		    WHERE LOWER(communication_medium)='email' AND sent_or_received='Received'
		    AND LOWER(sender) IN ({ph})""", params)[0][0]
	# контроль: сколько настоящих входящих (sender НЕ наш) — их не трогаем
	others = frappe.db.sql(
		f"""SELECT count(*) FROM `tabCommunication`
		    WHERE LOWER(communication_medium)='email' AND sent_or_received='Received'
		    AND LOWER(sender) NOT IN ({ph})""", params)[0][0]
	if not int(apply):
		return {"would_update_to_sent": int(cnt), "real_received_untouched": int(others), "applied": False}
	frappe.db.sql(
		f"""UPDATE `tabCommunication` SET sent_or_received='Sent'
		    WHERE LOWER(communication_medium)='email' AND sent_or_received='Received'
		    AND LOWER(sender) IN ({ph})""", params)
	frappe.db.commit()
	return {"updated_to_sent": int(cnt), "real_received_untouched": int(others), "applied": True}


@frappe.whitelist()
def dedup_by_message_id(apply=0):
	"""Дедуп (Задача 3): одно физическое письмо = одна Communication (по Message-ID).
	Оставляем самую раннюю запись, остальные дубли удаляем. apply=0 — только посчитать."""
	dups = frappe.db.sql(
		"""SELECT message_id, count(*) c FROM `tabCommunication`
		   WHERE LOWER(communication_medium)='email' AND message_id IS NOT NULL AND message_id!=''
		   GROUP BY message_id HAVING c > 1""", as_dict=True)
	to_delete = []
	for d in dups:
		rows = frappe.get_all("Communication", filters={"message_id": d.message_id},
		                      fields=["name"], order_by="creation asc")
		to_delete += [r.name for r in rows[1:]]
	if not int(apply):
		return {"dup_message_ids": len(dups), "would_delete": len(to_delete), "applied": False}
	for name in to_delete:
		frappe.delete_doc("Communication", name, ignore_permissions=True, force=True)
	frappe.db.commit()
	return {"deleted": len(to_delete), "applied": True}


@frappe.whitelist()
def reconcile_sender_names(limit: int = 2000):
	"""Проставить sender_full_name по From с сервера там, где имя пустое или = email.
	Бэкфилл (вручную) и go-forward (планировщик)."""
	updated = 0
	accounts = frappe.get_all("Email Account", filters={"enable_incoming": 1}, pluck="name")
	for an in accounts:
		acc = frappe.get_doc("Email Account", an)
		folders = ["INBOX"]
		sf = acc.get("sent_folder_name") or find_sent_folder(acc)
		if sf and sf not in folders:
			folders.append(sf)
		name_map = _imap_name_map(acc, folders)
		if not name_map:
			continue
		rows = frappe.db.sql(
			"""SELECT name, sender, message_id FROM `tabCommunication`
			   WHERE communication_medium='email' AND email_account=%s
			   AND message_id IS NOT NULL AND message_id!=''
			   AND (sender_full_name IS NULL OR sender_full_name='' OR sender_full_name=sender)
			   ORDER BY creation DESC LIMIT %s""",
			(an, int(limit)), as_dict=True,
		)
		for r in rows:
			real = name_map.get(_mid(r.message_id))
			if real and real != r.sender:
				frappe.db.set_value("Communication", r.name, "sender_full_name", real, update_modified=False)
				updated += 1
	frappe.db.commit()
	return {"updated": updated}
