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


# ---------------- Доборки в заказе ----------------

@frappe.whitelist()
def save_order_item(snapshot, thickness, plank_length, qty, coating=None, title=None):
	"""Сохранить доборку в заказ (Dobor Order Item) с серверным расчётом."""
	if isinstance(snapshot, str):
		snapshot = json.loads(snapshot)
	thickness = _pos_float(thickness, "Толщина, мм")
	plank_length = _pos_float(plank_length, "Длина планки, мм")
	qty = _pos_int(qty, "Количество, шт")
	flanges = snapshot.get("segs") or snapshot.get("flanges") or []
	hem_len = float(snapshot.get("hemLen") or 0)
	res = compute(flanges, bool(snapshot.get("hemLeft")), bool(snapshot.get("hemRight")),
	              hem_len, mass_per_sqm(thickness), plank_length, qty)
	doc = frappe.new_doc("Dobor Order Item")
	doc.title = (title or "").strip() or f"Доборка {res['developed_width']:g}мм"
	doc.coating = coating or None
	doc.thickness = thickness
	doc.plank_length = plank_length
	doc.qty = qty
	doc.developed_width = res["developed_width"]
	doc.weight_total = res["weight_total"]
	doc.profile_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
	doc.insert(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name, "developed_width": res["developed_width"], "weight_total": res["weight_total"]}


@frappe.whitelist()
def list_order_items():
	"""Доборки в заказе текущего пользователя (последние)."""
	return frappe.get_all("Dobor Order Item", filters={"owner": frappe.session.user},
	                      fields=["name", "title", "coating", "thickness", "plank_length", "qty",
	                              "developed_width", "weight_total", "profile_snapshot_json"],
	                      order_by="creation desc", limit=50)


@frappe.whitelist()
def delete_order_item(name):
	frappe.delete_doc("Dobor Order Item", name, ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True}
