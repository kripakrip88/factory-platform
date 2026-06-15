# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
API раскроя металла: накопление плана из калькулятора + расчёт (1D/2D) + рендер карт.
Изоляция: Cutting Plan / Cutting Plan Item не связаны с Item/Work Order/BOM ERP.
"""

import frappe
from frappe import _

from metal_calculator.cutting.linear import plan_linear
from metal_calculator.cutting.sheet import plan_sheet

LINEAR = "Линейный"
SHEET = "Листовой"
_PALETTE = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899",
            "#14B8A6", "#6366F1", "#0EA5E9", "#E2683C"]


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
def add_to_plan(cut_type, profile_type=None, size_label=None, piece_length=None, qty=None, piece_width=None):
	"""Добавить позицию в черновик плана раскроя текущего пользователя (создаёт при необходимости)."""
	if cut_type not in (LINEAR, SHEET):
		frappe.throw(_("Неизвестный тип раскроя: {0}").format(cut_type))
	piece_length = _pos_float(piece_length, "Длина детали, мм")
	qty = _pos_int(qty, "Количество, шт")
	if cut_type == SHEET:
		piece_width = _pos_float(piece_width, "Ширина детали, мм")

	# найти черновик нужного типа у текущего пользователя
	existing = frappe.get_all(
		"Cutting Plan",
		filters={"owner": frappe.session.user, "docstatus": 0, "cut_type": cut_type},
		order_by="modified desc", limit=1, pluck="name",
	)
	if existing:
		doc = frappe.get_doc("Cutting Plan", existing[0])
	else:
		doc = frappe.new_doc("Cutting Plan")
		doc.cut_type = cut_type
		doc.kerf = 3

	doc.append("items", {
		"profile_type": profile_type or ("Лист" if cut_type == SHEET else ""),
		"size_label": size_label or "",
		"piece_length": piece_length,
		"piece_width": piece_width if cut_type == SHEET else None,
		"qty": qty,
	})
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name, "cut_type": cut_type, "items": len(doc.items)}


@frappe.whitelist()
def calculate(plan_name):
	"""Рассчитать раскрой по плану. Размеры заготовки обязательны."""
	doc = frappe.get_doc("Cutting Plan", plan_name)
	if not doc.items:
		frappe.throw(_("В плане нет деталей"))
	kerf = float(doc.kerf or 0)
	if kerf < 0:
		frappe.throw(_("Ширина реза не может быть отрицательной"))

	items = [{
		"profile_type": it.profile_type, "size_label": it.size_label,
		"piece_length": it.piece_length, "piece_width": it.piece_width, "qty": it.qty,
	} for it in doc.items]

	if doc.cut_type == LINEAR:
		stock = _pos_float(doc.stock_length, "Длина хлыста, мм")
		result = plan_linear(stock, kerf, items)
		html = _render_linear(result, stock, kerf)
	elif doc.cut_type == SHEET:
		sl = _pos_float(doc.sheet_length, "Длина листа, мм")
		sw = _pos_float(doc.sheet_width, "Ширина листа, мм")
		result = plan_sheet(sl, sw, kerf, items)
		html = _render_sheet(result, sl, sw, kerf)
	else:
		frappe.throw(_("Неизвестный тип раскроя: {0}").format(doc.cut_type))

	doc.total_stock = result["total_stock"]
	doc.waste_percent = result["waste_percent"]
	doc.result_html = html
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"total_stock": result["total_stock"], "waste_percent": result["waste_percent"],
	        "html": html, "groups": result["groups"]}


# ---------------- Рендер карт ----------------

def _render_linear(result, stock, kerf):
	out = [f'<div class="cut-summary">Хлыстов всего: <b>{result["total_stock"]}</b> · '
	       f'Отход: <b>{result["waste_percent"]:g}%</b> · хлыст {stock:g} мм, рез {kerf:g} мм</div>']
	for g in result["groups"]:
		title = f'{g["profile_type"]} {g["size_label"]}'.strip()
		if g["error"]:
			out.append(f'<div class="cut-group cut-error"><b>{frappe.utils.escape_html(title)}</b>: '
			           f'⚠️ {frappe.utils.escape_html(g["error"])}</div>')
			continue
		rows = []
		for p in g["patterns"]:
			pieces = " + ".join("%g" % x for x in p["pieces"])
			rows.append(f'<div class="cut-pat">[{pieces} <span class="cut-w">+ {p["waste"]:g} отход</span>] '
			            f'×{p["count"]}</div>')
		out.append(f'<div class="cut-group"><div class="cut-gtitle">{frappe.utils.escape_html(title)} — '
		           f'{g["stock_count"]} хлыст(ов), отход {g["waste_percent"]:g}%</div>{"".join(rows)}</div>')
	return "".join(out)


def _render_sheet(result, sl, sw, kerf):
	out = [f'<div class="cut-summary">Листов всего: <b>{result["total_stock"]}</b> · '
	       f'Отход: <b>{result["waste_percent"]:g}%</b> · лист {sl:g}×{sw:g} мм, рез {kerf:g} мм</div>']
	for g in result["groups"]:
		title = f'Лист {g["size_label"]} мм'.strip()
		if g["error"]:
			out.append(f'<div class="cut-group cut-error"><b>{frappe.utils.escape_html(title)}</b>: '
			           f'⚠️ {frappe.utils.escape_html(g["error"])}</div>')
			continue
		out.append(f'<div class="cut-group"><div class="cut-gtitle">{frappe.utils.escape_html(title)} — '
		           f'{g["sheet_count"]} лист(ов), отход {g["waste_percent"]:g}%</div>')
		for idx, placements in enumerate(g["sheets"], start=1):
			out.append(f'<div class="cut-sheet-no">Лист №{idx}</div>')
			out.append(_svg_sheet(sl, sw, placements))
		out.append("</div>")
	return "".join(out)


def _svg_sheet(sl, sw, placements, max_w=520):
	scale = max_w / sl if sl else 1
	W = sl * scale
	H = sw * scale
	parts = [f'<rect x="0" y="0" width="{W:.1f}" height="{H:.1f}" fill="#e5e7eb" stroke="#9ca3af"/>']
	for i, p in enumerate(placements):
		x, y, w, h = p["x"] * scale, p["y"] * scale, p["w"] * scale, p["h"] * scale
		color = _PALETTE[i % len(_PALETTE)]
		# исходные размеры детали (учёт поворота для подписи)
		dl, dw = (p["w"], p["h"]) if not p.get("rot") else (p["h"], p["w"])
		label = f'{dl:g}×{dw:g}' + ("↻" if p.get("rot") else "")
		parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
		             f'fill="{color}" fill-opacity="0.78" stroke="#1f2937" stroke-width="0.7"/>')
		if w > 34 and h > 14:
			parts.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 4:.1f}" text-anchor="middle" '
			             f'font-size="11" fill="#fff">{label}</text>')
	return (f'<svg viewBox="0 0 {W:.1f} {H:.1f}" width="{W:.1f}" height="{H:.1f}" '
	        f'style="max-width:100%;height:auto;margin:6px 0;border-radius:4px">{"".join(parts)}</svg>')
