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


WORKSPACE = "Калькуляторы"


def _ensure_sidebar_and_icon():
	"""Создать Workspace Sidebar + Desktop Icon для показа в ВЕРХНЕМ меню saas_theme.

	КРИТИЧНО №3 (самое важное для навигации): тема saas_theme рисует ГОРИЗОНТАЛЬНОЕ
	верхнее меню, а НЕ стандартный левый сайдбар Frappe. Её get_workspaces()
	(saas_theme.js) берёт пункты из `frappe.boot.desktop_icons`, фильтр:
	  hidden != 1  И  link_type == "Workspace Sidebar"  И  есть workspace_sidebar_item[label].
	Значит для появления в меню нужны ДВЕ записи (создаёт обычно
	auto_generate_icons_and_sidebar, но она бежит ДО нашего after_install, когда
	воркспейса ещё нет — поэтому делаем сами):
	  1) Workspace Sidebar (секция меню) — module-less (виден всем),
	     standard=0 (migrate не удалит как орфан), items из shortcut'ов воркспейса.
	  2) Desktop Icon — link_type="Workspace Sidebar", link_to=секция, hidden=0,
	     standard=0. ИМЕННО его берёт верхнее меню.
	"""
	ws_doc = frappe.get_doc("Workspace", WORKSPACE)

	# --- Workspace Sidebar (секция) ---
	if frappe.db.exists("Workspace Sidebar", WORKSPACE):
		frappe.delete_doc("Workspace Sidebar", WORKSPACE, force=True, ignore_permissions=True)
	sidebar = frappe.new_doc("Workspace Sidebar")
	sidebar.title = WORKSPACE
	sidebar.header_icon = ws_doc.icon or "calculator"
	sidebar.standard = 0  # не модульная → видна всем, не удаляется migrate как орфан
	# первый пункт — сам воркспейс («Главная»), далее shortcut'ы
	sidebar.append("items", {"label": "Главная", "link_to": WORKSPACE, "link_type": "Workspace", "type": "Link", "idx": 0})
	for i, s in enumerate(ws_doc.shortcuts, start=1):
		sidebar.append("items", {"label": s.label, "link_to": s.link_to, "link_type": s.type, "type": "Link", "idx": i})
	sidebar.insert(ignore_permissions=True)

	# --- Desktop Icon (его берёт верхнее меню saas_theme) ---
	if frappe.db.exists("Desktop Icon", WORKSPACE):
		frappe.delete_doc("Desktop Icon", WORKSPACE, force=True, ignore_permissions=True)
	icon = frappe.new_doc("Desktop Icon")
	icon.update({
		"label": WORKSPACE,
		"link_to": WORKSPACE,
		"link_type": "Workspace Sidebar",
		"icon_type": "Link",
		"icon": ws_doc.icon or "calculator",
		"hidden": 0,
		"standard": 0,  # не удаляется migrate как орфан (фильтр орфанов — standard:True)
		"parent_icon": "ERPNext",
		"app": "metal_calculator",
		"idx": 1,
	})
	icon.insert(ignore_permissions=True)


def after_install():
	"""Заливаем справочники ГОСТ + воркспейс + секцию/иконку верхнего меню."""
	created = seed_all()
	_ensure_workspace()
	_ensure_sidebar_and_icon()
	frappe.logger().info(f"metal_calculator: seeded {created}, workspace+sidebar+icon ensured")
