# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

import json
import os

import frappe

from metal_calculator.seed import seed_all


def _ensure_workspace():
	"""Создать воркспейс «Калькуляторы» обычным insert (НЕ через fixtures).

	КРИТИЧНО №1: файл лежит в data/, а НЕ в fixtures/. Frappe v16 при install-app
	сам сканирует папку fixtures/ ПО ИМЕНАМ ФАЙЛОВ (игнорируя hooks `fixtures=[]`)
	и грузит их force-импортёром import_file_by_path → doc.insert(), который терял
	обязательное поле `type` у дочернего Workspace Shortcut → MandatoryError ещё
	ДО after_install. Поэтому workspace.json вынесен из fixtures/ в data/, а тут мы
	строим воркспейс сами с гарантией type у каждого shortcut. Идемпотентно.

	КРИТИЧНО №2: воркспейс БЕЗ `module`, но С `app="metal_calculator"`.
	Тонкий баланс двух механизмов Frappe v16:
	- remove_orphan_entities() на migrate удаляет public-воркспейс ТОЛЬКО если
	  заданы И module, И app (и нет стандартного файла). Оставляем module пустым →
	  фильтр не срабатывает, воркспейс переживает migrate.
	- get_workspace_sidebar_items() (desktop.py) показывает воркспейс в левой
	  навигации, группируя по `app`. Без app (и module) он выпадает из меню.
	  Поэтому ставим `app` напрямую. ВАЖНО: НЕ ставить `module` — иначе
	  Workspace.validate() сам выведет app из module → сработает фильтр орфанов.
	"""
	# Пересоздаём (delete+rebuild), а НЕ пропускаем если существует: воркспейс
	# module-less (см. КРИТИЧНО №2) → uninstall-app его не удаляет, он переживает
	# переустановку со старым набором shortcut'ов. Чтобы определение всегда
	# совпадало с data/workspace.json (новые ярлыки и т.п.) — сносим и строим заново.
	if frappe.db.exists("Workspace", "Калькуляторы"):
		frappe.delete_doc("Workspace", "Калькуляторы", force=True, ignore_permissions=True)
	path = os.path.join(os.path.dirname(__file__), "data", "workspace.json")
	with open(path, encoding="utf-8") as f:
		data = json.load(f)
	rec = (data if isinstance(data, list) else [data])[0]

	# Строим воркспейс ЯВНО: shortcut'ы добавляем через append с гарантированным
	# type у каждого. (Через get_doc(rec)/fixtures Frappe v16 терял обязательное
	# поле type у дочернего Workspace Shortcut → MandatoryError.)
	# `module` НЕ копируем намеренно (см. КРИТИЧНО №2) — иначе migrate удалит орфан.
	# `app` копируем — нужен для показа в навигации (группировка сайдбара по app).
	ws = frappe.new_doc("Workspace")
	for key in (
		"name", "label", "title", "app", "public", "is_hidden",
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
