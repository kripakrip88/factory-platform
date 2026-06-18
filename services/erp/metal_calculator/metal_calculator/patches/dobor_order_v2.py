# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Патч: переход доборок на модель «заказ + позиции».

Dobor Order Item стал чайлд-таблицей (istable). Старые плоские записи (создавались
прежним save_order_item — отдельными документами, без parent) теперь осиротели:
это тестовые данные, удаляем, чтобы не мусорили. Идемпотентно.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Dobor Order Item"):
		return
	# удалить осиротевшие плоские записи (нет parent — не принадлежат ни одному Dobor Order)
	orphans = frappe.db.sql(
		"""SELECT name FROM `tabDobor Order Item`
		   WHERE COALESCE(parent, '') = '' OR COALESCE(parenttype, '') = ''"""
	)
	for (name,) in orphans:
		frappe.db.delete("Dobor Order Item", {"name": name})
	frappe.db.commit()
