# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
Расчёт веса металлопроката. БЕЗ геометрии — только выборка из справочника ГОСТ
и умножение. Размеры заготовки пользователь вводит в МИЛЛИМЕТРАХ; справочные
веса — в кг/м и кг/м². Конвертация мм→м делается ЗДЕСЬ, явно.

Марка стали в арифметике не участвует — только прокидывается в ответ как атрибут.
"""

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


@frappe.whitelist()
def calculate(mode, ref, qty, length_mm=None, a_mm=None, b_mm=None, steel_grade=None):
	"""
	mode: "linear" (линейный прокат) | "sheet" (лист)
	ref:  имя записи Metal Profile (linear) или Metal Sheet Grade (sheet)
	qty:  количество, шт (> 0, целое)
	linear: length_mm — длина заготовки, мм
	sheet:  a_mm, b_mm — стороны листа, мм
	steel_grade: имя Steel Grade (атрибут, на вес не влияет)
	"""
	qty = _pos_int(qty, "Количество, шт")

	if mode == "linear":
		length_mm = _pos_float(length_mm, "Длина L, мм")
		mass_per_meter = frappe.db.get_value("Metal Profile", ref, "mass_per_meter")
		if mass_per_meter is None:
			frappe.throw(_("Профиль «{0}» не найден в справочнике").format(ref))
		weight_one = float(mass_per_meter) * (length_mm / 1000.0)  # мм → м

	elif mode == "sheet":
		a_mm = _pos_float(a_mm, "Сторона a, мм")
		b_mm = _pos_float(b_mm, "Сторона b, мм")
		mass_per_sqm = frappe.db.get_value("Metal Sheet Grade", ref, "mass_per_sqm")
		if mass_per_sqm is None:
			frappe.throw(_("Лист «{0}» не найден в справочнике").format(ref))
		weight_one = float(mass_per_sqm) * (a_mm / 1000.0) * (b_mm / 1000.0)  # мм → м

	else:
		frappe.throw(_("Неизвестный режим расчёта: {0}").format(mode))

	# Марка стали — только атрибут, в арифметике не участвует.
	grade = None
	if steel_grade:
		grade = frappe.db.get_value("Steel Grade", steel_grade, "grade") or steel_grade

	return {
		"weight_one_kg": round(weight_one, 3),
		"weight_total_kg": round(weight_one * qty, 3),
		"qty": qty,
		"steel_grade": grade,
		"unit": "кг",
	}
