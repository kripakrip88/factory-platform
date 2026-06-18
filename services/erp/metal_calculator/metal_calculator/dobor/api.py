# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
Доборные элементы: расчёт развёртки/веса (server-side). Логика — как в прототипе.
Поправку на гиб НЕ применяем. Вес — через Metal Sheet Grade (для стали т×7.85).
Изоляция: доборные доктайпы не связаны с Item/BOM/Work Order ERP.
"""

import json

import frappe
from frappe import _


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


def mass_per_sqm(thickness):
	"""Масса 1 м² по толщине: из справочника Metal Sheet Grade (гладкий), иначе т×7.85."""
	val = frappe.db.get_value(
		"Metal Sheet Grade", {"thickness": thickness, "sheet_type": "Гладкий"}, "mass_per_sqm"
	)
	return float(val) if val else thickness * 7.85


def compute(flanges, hem_left, hem_right, hem_len, mps, plank_length, qty, coil_width=0):
	"""ЧИСТЫЙ расчёт (без frappe) — для тестов. mps — масса 1 м² (кг)."""
	flange_sum = sum(float(f.get("len") or 0) for f in (flanges or []))
	hem_count = (1 if hem_left else 0) + (1 if hem_right else 0)
	developed = flange_sum + hem_count * hem_len
	area_one = (developed / 1000.0) * (plank_length / 1000.0)  # м²
	weight_one = area_one * mps
	# каждая завальцовка считается как гиб (подгиб 180°)
	bends = max(0, len(flanges or []) - 1) + hem_count
	strips = int(coil_width // developed) if (developed > 0 and coil_width > 0) else 0
	strip_waste = (coil_width - strips * developed) if strips else (coil_width if coil_width > 0 else 0)
	return {
		"developed_width": round(developed, 2),
		"flange_sum": round(flange_sum, 2),
		"hem_total": round(hem_count * hem_len, 2),
		"flanges_count": len(flanges or []),
		"bends": bends,
		"area_one": round(area_one, 4),
		"weight_one": round(weight_one, 3),
		"weight_total": round(weight_one * qty, 3),
		"mass_per_sqm": round(mps, 3),
		"strips": strips,
		"strip_waste": round(strip_waste, 2),
	}


@frappe.whitelist()
def calc(profile):
	"""Расчёт доборки. profile — JSON: {flanges:[{len,dir}], hem_left, hem_right, hem_len,
	thickness, plank_length, qty, coil_width}. Размеры в мм."""
	if isinstance(profile, str):
		profile = json.loads(profile)
	thickness = _pos_float(profile.get("thickness"), "Толщина, мм")
	plank_length = _pos_float(profile.get("plank_length"), "Длина планки, мм")
	qty = _pos_int(profile.get("qty"), "Количество, шт")
	hem_len = float(profile.get("hem_len") or 0)
	coil = float(profile.get("coil_width") or 0)
	return compute(
		profile.get("flanges") or [], bool(profile.get("hem_left")), bool(profile.get("hem_right")),
		hem_len, mass_per_sqm(thickness), plank_length, qty, coil,
	)


# ---------------- Справочники для UI ----------------

@frappe.whitelist()
def list_coatings():
	"""Покрытия для выпадашки цвета."""
	return frappe.get_all("Dobor Coating", fields=["name", "coating_name", "ral_code", "hex"],
	                      order_by="coating_name asc")


@frappe.whitelist()
def list_templates():
	"""Библиотека профилей (шаблоны сечения)."""
	return frappe.get_all("Dobor Profile", fields=[
		"name", "profile_name", "flanges_json", "hem_left", "hem_right",
		"hem_left_dir", "hem_right_dir", "hem_len", "lock", "paint_side",
	], order_by="profile_name asc")


@frappe.whitelist()
def save_template(profile_name, snapshot):
	"""Сохранить текущий профиль в библиотеку шаблонов (Dobor Profile)."""
	if isinstance(snapshot, str):
		snapshot = json.loads(snapshot)
	flanges = snapshot.get("segs") or snapshot.get("flanges") or []
	doc = frappe.new_doc("Dobor Profile")
	doc.profile_name = (profile_name or "").strip() or "Профиль"
	doc.flanges_json = json.dumps(flanges, ensure_ascii=False)
	doc.hem_left = 1 if snapshot.get("hemLeft") else 0
	doc.hem_right = 1 if snapshot.get("hemRight") else 0
	doc.hem_left_dir = int(snapshot.get("hemLeftDir") or 1)
	doc.hem_right_dir = int(snapshot.get("hemRightDir") or -1)
	doc.hem_len = float(snapshot.get("hemLen") or 15)
	doc.lock = 1 if snapshot.get("lockOn") else 0
	doc.paint_side = int(snapshot.get("paintSide") or 1)
	doc.insert(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def delete_template(name):
	frappe.delete_doc("Dobor Profile", name, ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True}


# ---------------- Заказы доборок (Dobor Order + позиции) ----------------

def _coating_or_none(value):
	"""Покрытие — Link на Dobor Coating; ставим только если такое есть."""
	if value and frappe.db.exists("Dobor Coating", value):
		return value
	return None


@frappe.whitelist()
def save_order(items, customer=None, order_date=None, order_name=None, status=None):
	"""Создать/обновить заказ доборок (Dobor Order) с позициями-снимками.

	items — JSON список [{snapshot, thickness, plank_length, qty, coating, title}].
	Если order_name задан — перезаписывает позиции существующего заказа.
	Числа считает validate() парента из снимка (единый источник истины с calc).
	"""
	if isinstance(items, str):
		items = json.loads(items)
	if order_name and frappe.db.exists("Dobor Order", order_name):
		doc = frappe.get_doc("Dobor Order", order_name)
		doc.set("items", [])
	else:
		doc = frappe.new_doc("Dobor Order")
	if customer is not None:
		doc.customer = customer
	if order_date:
		doc.order_date = order_date
	if status:
		doc.status = status
	for it in (items or []):
		snap = it.get("snapshot")
		snap_str = snap if isinstance(snap, str) else json.dumps(snap or {}, ensure_ascii=False)
		doc.append("items", {
			"title": (it.get("title") or "").strip() or "Доборка",
			"coating": _coating_or_none(it.get("coating")),
			"thickness": _pos_float(it.get("thickness"), "Толщина, мм"),
			"plank_length": _pos_float(it.get("plank_length"), "Длина планки, мм"),
			"qty": _pos_int(it.get("qty"), "Количество, шт"),
			"profile_snapshot_json": snap_str,
		})
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name, "total_weight": doc.total_weight,
	        "total_positions": doc.total_positions, "total_qty": doc.total_qty}


@frappe.whitelist()
def list_orders():
	"""Список заказов доборок (общий, не по owner — как спецификации металла)."""
	return frappe.get_all("Dobor Order", fields=[
		"name", "customer", "order_date", "status",
		"total_positions", "total_qty", "total_area", "total_weight",
	], order_by="modified desc", limit=50)


@frappe.whitelist()
def get_order(name):
	"""Полный заказ с позициями — для загрузки обратно в конструктор."""
	doc = frappe.get_doc("Dobor Order", name)
	return {
		"name": doc.name, "customer": doc.customer, "order_date": str(doc.order_date or ""),
		"status": doc.status, "total_positions": doc.total_positions, "total_qty": doc.total_qty,
		"total_area": doc.total_area, "total_weight": doc.total_weight,
		"items": [{
			"title": it.title, "coating": it.coating, "thickness": it.thickness,
			"plank_length": it.plank_length, "qty": it.qty, "developed_width": it.developed_width,
			"area_total": it.area_total, "weight_total": it.weight_total,
			"profile_snapshot_json": it.profile_snapshot_json,
		} for it in doc.items],
	}


@frappe.whitelist()
def delete_order(name):
	frappe.delete_doc("Dobor Order", name, ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True}
