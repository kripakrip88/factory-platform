# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
API раскроя металла: накопление плана из калькулятора + расчёт (1D/2D) + рендер карт.
Изоляция: Cutting Plan / Cutting Plan Item не связаны с Item/Work Order/BOM ERP.
"""

import json

import frappe
from frappe import _

from metal_calculator.cutting.linear import plan_linear
from metal_calculator.cutting.sheet import plan_sheet

LINEAR = "Линейный"
SHEET = "Листовой"


def _pos_float(value, label):
	try:
		num = float(value)
	except (TypeError, ValueError):
		frappe.throw(_("Поле «{0}» должно быть числом").format(label))
	if num <= 0:
		frappe.throw(_("Поле «{0}» должно быть больше нуля").format(label))
	return num


def _pos_int(value, label):
	try:
		num = int(float(value))
	except (TypeError, ValueError):
		frappe.throw(_("Поле «{0}» должно быть целым числом").format(label))
	if num <= 0:
		frappe.throw(_("Поле «{0}» должно быть больше нуля").format(label))
	return num


@frappe.whitelist()
def add_to_plan(cut_type, profile_type=None, size_label=None, piece_length=None, qty=None, piece_width=None):
	"""Добавить позицию в черновик плана раскроя текущего пользователя (создаёт при необходимости)."""
	if cut_type not in (LINEAR, SHEET):
		frappe.throw(_("Неизвестный тип раскроя: {0}").format(cut_type))
	piece_length = _pos_float(piece_length, "Длина детали, мм")
	qty = _pos_int(qty, "Количество, шт")
	if cut_type == SHEET:
		piece_width = _pos_float(piece_width, "Ширина детали, мм")

	# найти черновик нужного типа у текущего пользователя
	existing = frappe.get_all(
		"Cutting Plan",
		filters={"owner": frappe.session.user, "docstatus": 0, "cut_type": cut_type},
		order_by="modified desc", limit=1, pluck="name",
	)
	if existing:
		doc = frappe.get_doc("Cutting Plan", existing[0])
	else:
		doc = frappe.new_doc("Cutting Plan")
		doc.cut_type = cut_type
		doc.kerf = 3

	doc.append("items", {
		"profile_type": profile_type or ("Лист" if cut_type == SHEET else ""),
		"size_label": size_label or "",
		"piece_length": piece_length,
		"piece_width": piece_width if cut_type == SHEET else None,
		"qty": qty,
	})
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name, "cut_type": cut_type, "items": len(doc.items)}


@frappe.whitelist()
def calculate(plan_name):
	"""Рассчитать раскрой по плану. Размеры заготовки обязательны."""
	doc = frappe.get_doc("Cutting Plan", plan_name)
	if not doc.items:
		frappe.throw(_("В плане нет деталей"))
	kerf = float(doc.kerf or 0)
	if kerf < 0:
		frappe.throw(_("Ширина реза не может быть отрицательной"))

	items = [{
		"profile_type": it.profile_type, "size_label": it.size_label,
		"piece_length": it.piece_length, "piece_width": it.piece_width, "qty": it.qty,
	} for it in doc.items]

	meta = {"cut_type": doc.cut_type, "kerf": kerf}
	if doc.cut_type == LINEAR:
		meta["stock_length"] = _pos_float(doc.stock_length, "Длина хлыста, мм")
		result = plan_linear(meta["stock_length"], kerf, items)
	elif doc.cut_type == SHEET:
		meta["sheet_length"] = _pos_float(doc.sheet_length, "Длина листа, мм")
		meta["sheet_width"] = _pos_float(doc.sheet_width, "Ширина листа, мм")
		result = plan_sheet(meta["sheet_length"], meta["sheet_width"], kerf, items)
	else:
		frappe.throw(_("Неизвестный тип раскроя: {0}").format(doc.cut_type))

	payload = {"meta": meta, "result": result}
	doc.total_stock = result["total_stock"]
	doc.waste_percent = result["waste_percent"]
	# Храним СТРУКТУРУ как JSON (не HTML) — карты рисует клиент (cutting_plan.js),
	# иначе Frappe-санитайзер вырезает fill/style у SVG → чёрные эскизы.
	doc.result_html = json.dumps(payload, ensure_ascii=False)
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"total_stock": result["total_stock"], "waste_percent": result["waste_percent"], "payload": payload}
