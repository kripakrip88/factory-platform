# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Идемпотентная заливка справочников из seed_data. Безопасно перезапускать."""

import frappe

from metal_calculator.seed_data import GRADES, PROFILES, SHEETS


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
		frappe.get_doc(
			{
				"doctype": "Metal Profile",
				"profile_type": profile_type,
				"gost": gost,
				"size_label": size_label,
				"mass_per_meter": mass,
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
