import frappe
from erpnext.crm.doctype.lead.lead import make_opportunity as _erpnext_make_opportunity


@frappe.whitelist()
def make_opportunity(source_name, target_doc=None):
	"""Лид → Сделка с переносом заводских полей.

	Скалярные заводские поля (mw_estimated_volume / mw_desired_delivery_date /
	mw_drawing_status) переносит сам get_mapped_doc внутри штатного
	make_opportunity — он копирует поля с одинаковым fieldname автоматически.

	Табличное поле mw_product_categories (Table MultiSelect) get_mapped_doc НЕ
	копирует, поэтому переносим его строки здесь. Делегируем всё остальное
	родному make_opportunity, чтобы маппинг пережил обновления erpnext.

	Подключается через override_whitelisted_methods в hooks.py — кнопка
	«Создать → Сделка» на форме лида зовёт исходный путь, который перехватывается.
	"""
	target = _erpnext_make_opportunity(source_name, target_doc)

	lead = frappe.get_doc("Lead", source_name)
	categories = lead.get("mw_product_categories") or []
	if categories:
		target.set("mw_product_categories", [])
		for row in categories:
			if row.product_category:
				target.append("mw_product_categories", {"product_category": row.product_category})

	return target
