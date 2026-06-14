import frappe


@frappe.whitelist()
def set_classification(name, classification, reason=""):
	"""Записать результат авто-классификации письма в обход валидации документа.

	n8n-труба классификации пишет результат в кастомные поля Communication.
	Обычный REST PUT делает полное сохранение документа → запускает валидацию,
	которая падает на письмах с кривым адресом отправителя
	(InvalidEmailAddressError, напр. дублированный `<pmkpark@mail.ru> <...>`).
	Эти поля — служебная разметка классификатора, не часть бизнес-данных письма,
	поэтому пишем напрямую через db.set_value без валидации и без modified-стампа.
	"""
	if not frappe.db.exists("Communication", name):
		frappe.throw(f"Communication {name} not found", frappe.DoesNotExistError)

	frappe.db.set_value(
		"Communication",
		name,
		{
			"custom_claude_classification": classification,
			"custom_claude_reason": reason or "",
		},
		update_modified=False,
	)
	frappe.db.commit()
	return {"ok": True, "name": name, "classification": classification}
