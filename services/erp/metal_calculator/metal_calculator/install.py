# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

import json
import os

import frappe

from metal_calculator.seed import seed_all


def _ensure_workspace():
	"""Создать воркспейс «Калькуляторы» обычным insert (НЕ через fixtures).

	force-импортёр Frappe v16 (import_file_by_path) терял обязательное поле `type`
	у дочернего Workspace Shortcut → MandatoryError. Обычный get_doc().insert()
	сохраняет дочерние поля корректно. Идемпотентно. Источник данных — тот же
	файл fixtures/workspace.json (единый источник).
	"""
	if frappe.db.exists("Workspace", "Калькуляторы"):
		return
	path = os.path.join(os.path.dirname(__file__), "fixtures", "workspace.json")
	with open(path, encoding="utf-8") as f:
		data = json.load(f)
	rec = (data if isinstance(data, list) else [data])[0]

	# Строим воркспейс ЯВНО: shortcut'ы добавляем через append с гарантированным
	# type у каждого. (Через get_doc(rec)/fixtures Frappe v16 терял обязательное
	# поле type у дочернего Workspace Shortcut → MandatoryError.)
	ws = frappe.new_doc("Workspace")
	for key in (
		"name", "label", "title", "module", "public", "is_hidden",
		"icon", "indicator_color", "sequence_id", "content",
	):
		if rec.get(key) is not None:
			ws.set(key, rec[key])
	for s in rec.get("shortcuts", []):
		ws.append("shortcuts", {
			"type": s.get("type") or "Page",
			"label": s.get("label"),
			"link_to": s.get("link_to"),
			"color": s.get("color"),
			"doc_view": s.get("doc_view", ""),
		})
	for link in rec.get("links", []):
		ws.append("links", link)
	ws.insert(ignore_permissions=True)


def after_install():
	"""Заливаем справочники ГОСТ + создаём воркспейс сразу после установки аппы."""
	created = seed_all()
	_ensure_workspace()
	frappe.logger().info(f"metal_calculator: seeded {created}, workspace ensured")
