import frappe
from erpnext.crm.doctype.lead.lead import (
	make_lead_from_communication as _erpnext_make_lead_from_communication,
)


@frappe.whitelist()
def make_lead_from_communication(communication, ignore_communication_links=False):
	"""Создать лид из письма + перенести вложения письма в лид.

	Штатный erpnext.make_lead_from_communication создаёт/находит лид и линкует к
	нему письмо, но File-вложения остаются привязанными только к Communication —
	лид рождается без чертежей, менеджеру приходится возвращаться в письмо
	(ломает «единое окно»). Здесь делегируем создание лида родной функции, затем
	КОПИРУЕМ привязку файлов на лид (физический файл один, привязок две — письмо
	не лишается вложений).

	Подключается через override_whitelisted_methods в hooks.py — кнопка
	«Создать → Лид» на карточке письма зовёт исходный путь, который
	перехватывается. Тот же метод сможет звать n8n при авто-создании лидов.
	"""
	lead_name = _erpnext_make_lead_from_communication(communication, ignore_communication_links)

	# Перенос вложений изолирован в try/except: даже если File-операция упадёт
	# (напр. на письме с битыми заголовками), лид уже создан и не откатывается.
	if lead_name:
		try:
			copy_attachment_links("Communication", communication, "Lead", lead_name)
		except Exception:
			frappe.log_error(
				title="saas_theme: перенос вложений письма в лид не удался",
				message=frappe.get_traceback(),
			)

	return lead_name


def copy_attachment_links(from_doctype, from_name, to_doctype, to_name):
	"""Скопировать привязку File-вложений с одного документа на другой.

	Создаёт новые File-записи на ТОТ ЖЕ file_url (физический файл не дублируется).
	Идемпотентно: пропускает файл, уже привязанный к цели. Не трогает исходный
	документ — устойчиво к письмам, которые не проходят валидацию Communication.
	"""
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": from_doctype, "attached_to_name": from_name},
		fields=["file_url", "file_name", "is_private"],
	)
	copied = 0
	for f in files:
		if not f.file_url:
			continue
		already = frappe.db.exists(
			"File",
			{
				"attached_to_doctype": to_doctype,
				"attached_to_name": to_name,
				"file_url": f.file_url,
			},
		)
		if already:
			continue
		frappe.get_doc(
			{
				"doctype": "File",
				"file_url": f.file_url,
				"file_name": f.file_name,
				"is_private": f.is_private,
				"attached_to_doctype": to_doctype,
				"attached_to_name": to_name,
			}
		).insert(ignore_permissions=True)
		copied += 1
	return copied
