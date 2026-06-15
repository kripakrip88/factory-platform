# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Идемпотентная заливка справочников из seed_data. Безопасно перезапускать."""

import re

import frappe

from metal_calculator.seed_data import GRADES, PROFILES, SHEETS

# Разделители размеров в типоразмере: латинская x, кириллическая х, ×
_DIM_SPLIT = re.compile(r"[x×х]", re.IGNORECASE)


def _parse_dims(size_label):
	"""Разобрать типоразмер на (wall_mm, height_mm, width_mm).

	Нормализация: для AxB высота = БОЛЬШИЙ габарит, ширина = меньший — поэтому
	100x50 и 50x100 дают одинаковые height/width (одна позиция при поиске).
	Где параметр неприменим — None. Двутавр/швеллер (номерные типоразмеры вроде
	«20Б1», «16У») не парсятся → все три None, поиск по типоразмеру.
	"""
	s = (size_label or "").strip().replace(" бесш", "").strip()
	low = s.lower()
	parts = _DIM_SPLIT.split(s)
	if len(parts) == 3:  # AxBxt — уголок, профильная труба
		try:
			a, b, t = (float(p) for p in parts)
			return t, max(a, b), min(a, b)
		except ValueError:
			pass
	elif len(parts) == 2:  # DxT — труба круглая (наружный × стенка)
		try:
			d, t = (float(p) for p in parts)
			return t, d, None
		except ValueError:
			pass
	if low.startswith(("d", "s")):  # круг/арматура «d20», шестигранник «S24»
		try:
			return None, float(s[1:]), None
		except ValueError:
			pass
	try:  # чистое число — квадрат
		v = float(s)
		return None, v, v
	except ValueError:
		return None, None, None


def seed_all():
	"""Залить все справочники. Возвращает счётчики созданного."""
	created = {
		"Metal Profile": _seed_profiles(),
		"Metal Sheet Grade": _seed_sheets(),
		"Steel Grade": _seed_grades(),
	}
	frappe.db.commit()
	return created


def _seed_profiles():
	n = 0
	for profile_type, gost, size_label, mass in PROFILES:
		name = f"{profile_type}-{size_label}"
		if frappe.db.exists("Metal Profile", name):
			continue
		wall, height, width = _parse_dims(size_label)
		frappe.get_doc(
			{
				"doctype": "Metal Profile",
				"profile_type": profile_type,
				"gost": gost,
				"size_label": size_label,
				"mass_per_meter": mass,
				"wall_mm": wall,
				"height_mm": height,
				"width_mm": width,
			}
		).insert(ignore_permissions=True)
		n += 1
	return n


def _seed_sheets():
	n = 0
	for sheet_type, thickness, size_label, gost, mass in SHEETS:
		# Идемпотентность по (тип, толщина, типоразмер) — имя формирует контроллер
		# autoname по этим же полям, поэтому проверяем по ним, а не по имени.
		if frappe.db.exists(
			"Metal Sheet Grade",
			{"sheet_type": sheet_type, "thickness": thickness, "size_label": size_label or ""},
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Metal Sheet Grade",
				"sheet_type": sheet_type,
				"thickness": thickness,
				"size_label": size_label,
				"gost": gost,
				"mass_per_sqm": mass,
			}
		).insert(ignore_permissions=True)
		n += 1
	return n


def _seed_grades():
	n = 0
	for grade, standard, is_default in GRADES:
		if frappe.db.exists("Steel Grade", grade):
			continue
		frappe.get_doc(
			{
				"doctype": "Steel Grade",
				"grade": grade,
				"standard": standard,
				"is_default": is_default,
			}
		).insert(ignore_permissions=True)
		n += 1
	return n
