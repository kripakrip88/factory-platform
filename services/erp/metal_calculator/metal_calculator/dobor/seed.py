# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Сид справочника покрытий доборки (Цинк + RAL). Идемпотентно."""

import frappe

# (coating_name, ral_code, hex). RAL — открытый промышленный стандарт нумерации.
COATINGS = [
	("Цинк", "", "#b9c2cc"),
	("RAL 3005 Вино", "3005", "#5e1a26"),
	("RAL 8017 Шоколад", "8017", "#3a2419"),
	("RAL 6005 Зелёный мох", "6005", "#114232"),
	("RAL 9003 Белый", "9003", "#f1f0ea"),
	("RAL 7024 Графит", "7024", "#45494e"),
	("RAL 1015 Сл. кость", "1015", "#e6d2b5"),
	("RAL 5005 Синий", "5005", "#1f3a93"),
]


def seed_coatings():
	n = 0
	for name, ral, hx in COATINGS:
		if frappe.db.exists("Dobor Coating", name):
			continue
		frappe.get_doc({
			"doctype": "Dobor Coating", "coating_name": name, "ral_code": ral, "hex": hx,
		}).insert(ignore_permissions=True)
		n += 1
	frappe.db.commit()
	return n
