# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
API раскроя металла: создание плана из спецификации (со связью) + расчёт (смешанный
1D+2D в одном плане) + отдача структуры карт. Изоляция: Cutting Plan / Cutting Plan
Item не связаны с Item/Work Order/BOM ERP (есть мягкая ссылка на Metal Spec).
"""

import json

import frappe
from frappe import _

from metal_calculator.cutting.linear import plan_linear
from metal_calculator.cutting.sheet import plan_sheet

SHEET_FORM = "Лист"


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


def _is_sheet(it):
	return (it.get("form") or it.get("profile_type")) == SHEET_FORM or bool(it.get("piece_width"))


@frappe.whitelist()
def create_cutting_from_spec(items, customer=None):
	"""Единый поток из калькулятора: сохранить Metal Spec + создать СВЯЗАННЫЙ
	смешанный план раскроя (линейные + листовые позиции в одном документе).

	items — JSON-строка позиций калькулятора. Возвращает {spec, plan}.
	"""
	if isinstance(items, str):
		items = json.loads(items)
	if not items:
		frappe.throw(_("Спецификация пустая — нечего сохранять"))

	# 1) Сохранить спецификацию (Metal Spec)
	spec = frappe.new_doc("Metal Spec")
	if customer:
		spec.customer = customer
	for it in items:
		spec.append("items", {
			"detail_name": it.get("detail_name"),
			"form": it.get("form"), "item_ref": it.get("item_ref"),
			"size_label": it.get("size_label"), "steel_grade": it.get("steel_grade"),
			"dims": it.get("dims"), "qty": it.get("qty"),
			"weight_one_kg": it.get("weight_one_kg"), "weight_total_kg": it.get("weight_total_kg"),
		})
	spec.save(ignore_permissions=False)

	# 2) Создать смешанный план раскроя со ссылкой на спеку
	has_sheet = any(_is_sheet(it) for it in items)
	has_linear = any(not _is_sheet(it) for it in items)
	if has_sheet and has_linear:
		cut_type = "Смешанный"
	elif has_sheet:
		cut_type = "Листовой"
	else:
		cut_type = "Линейный"

	plan = frappe.new_doc("Cutting Plan")
	plan.metal_spec = spec.name
	plan.cut_type = cut_type
	plan.kerf = 3
	plan.plan_title = f"Раскрой по {spec.name}"
	for it in items:
		plan.append("items", {
			"detail_name": it.get("detail_name"),
			"profile_type": it.get("form") or "",
			"size_label": it.get("size_label") or "",
			"piece_length": it.get("piece_length"),
			"piece_width": it.get("piece_width") if _is_sheet(it) else None,
			"qty": it.get("qty"),
		})
	plan.save(ignore_permissions=False)
	frappe.db.commit()
	return {"spec": spec.name, "plan": plan.name, "cut_type": cut_type}


@frappe.whitelist()
def add_to_plan(cut_type, profile_type=None, size_label=None, piece_length=None, qty=None,
                piece_width=None, detail_name=None):
	"""Добавить одну позицию в черновик плана пользователя (старый поштучный путь)."""
	piece_length = _pos_float(piece_length, "Длина детали, мм")
	qty = _pos_int(qty, "Количество, шт")
	is_sheet = cut_type == "Листовой"
	if is_sheet:
		piece_width = _pos_float(piece_width, "Ширина детали, мм")
	existing = frappe.get_all("Cutting Plan", filters={
		"owner": frappe.session.user, "docstatus": 0, "cut_type": cut_type, "metal_spec": ["is", "not set"],
	}, order_by="modified desc", limit=1, pluck="name")
	if existing:
		doc = frappe.get_doc("Cutting Plan", existing[0])
	else:
		doc = frappe.new_doc("Cutting Plan")
		doc.cut_type = cut_type
		doc.kerf = 3
	doc.append("items", {
		"detail_name": detail_name, "profile_type": profile_type or ("Лист" if is_sheet else ""),
		"size_label": size_label or "", "piece_length": piece_length,
		"piece_width": piece_width if is_sheet else None, "qty": qty,
	})
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name, "items": len(doc.items)}


@frappe.whitelist()
def calculate(plan_name):
	"""Рассчитать раскрой (смешанный: линейные + листовые в одном плане).

	Линейные позиции → нужна длина хлыста; листовые → размеры листа. Считаются
	только те части, для которых заданы размеры заготовки. Возвращает структуру
	(карты рисует клиент).
	"""
	doc = frappe.get_doc("Cutting Plan", plan_name)
	if not doc.items:
		frappe.throw(_("В плане нет деталей"))
	kerf = float(doc.kerf or 0)
	if kerf < 0:
		frappe.throw(_("Ширина реза не может быть отрицательной"))

	rows = [{
		"detail_name": it.detail_name, "profile_type": it.profile_type, "form": it.profile_type,
		"size_label": it.size_label, "piece_length": it.piece_length,
		"piece_width": it.piece_width, "qty": it.qty,
	} for it in doc.items]

	linear_items = [r for r in rows if not _is_sheet(r)]
	sheet_items = [r for r in rows if _is_sheet(r)]

	payload = {"kerf": kerf, "linear": None, "sheet": None}
	total_stock = 0

	if linear_items:
		stock = _pos_float(doc.stock_length, "Длина хлыста, мм")
		res = plan_linear(stock, kerf, linear_items)
		payload["linear"] = {"meta": {"stock_length": stock}, "result": res}
		total_stock += res["total_stock"]
	if sheet_items:
		sl = _pos_float(doc.sheet_length, "Длина листа, мм")
		sw = _pos_float(doc.sheet_width, "Ширина листа, мм")
		res = plan_sheet(sl, sw, kerf, sheet_items)
		payload["sheet"] = {"meta": {"sheet_length": sl, "sheet_width": sw}, "result": res}
		total_stock += res["total_stock"]

	# суммарный % отхода (по доле незанятого в обеих частях — для общей сводки)
	waste_parts = [p["result"]["waste_percent"] for p in (payload["linear"], payload["sheet"]) if p]
	overall_waste = round(sum(waste_parts) / len(waste_parts), 2) if waste_parts else 0.0

	doc.total_stock = total_stock
	doc.waste_percent = overall_waste
	doc.result_html = json.dumps(payload, ensure_ascii=False)  # JSON, не HTML — рисует клиент
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"total_stock": total_stock, "waste_percent": overall_waste, "payload": payload}
