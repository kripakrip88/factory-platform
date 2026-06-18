# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Производственный лист доборных элементов (PDF).

Эскизы сечений рисуются server-side из profile_snapshot_json (порт прототипа
dobor-report.html: verts/bend/flange/drawSketch/hem). Числа — через compute()
(единый источник истины с конструктором и calc). Документ строго ч/б.
"""

import json
import math
from html import escape

import frappe
from frappe import _

from metal_calculator.dobor.api import compute, mass_per_sqm

SHEET_W_MM = 1250  # лист по умолчанию
SHEET_L_MM = 2500
SHEET_AREA = (SHEET_W_MM / 1000.0) * (SHEET_L_MM / 1000.0)  # м²


# ---------------- геометрия (порт прототипа) ----------------

def _verts(start, segs):
	v = [{"x": start.get("x", 0), "y": start.get("y", 0)}]
	cur = {"x": v[0]["x"], "y": v[0]["y"]}
	for s in segs:
		r = math.radians(s.get("dir", 0))
		cur = {"x": cur["x"] + s["len"] * math.cos(r), "y": cur["y"] - s["len"] * math.sin(r)}
		v.append({"x": cur["x"], "y": cur["y"]})
	return v


def _bend(segs, i):
	d = segs[i].get("dir", 0) - segs[i - 1].get("dir", 0)
	while d > 180:
		d -= 360
	while d < -180:
		d += 360
	return d


def _flange(segs, i):
	return 180 - abs(_bend(segs, i))


def _fnum(x):
	return f"{x:.2f}"


def sketch_svg(snapshot):
	"""Монохромный мини-эскиз сечения (SVG-строка) из снимка профиля."""
	segs = snapshot.get("segs") or snapshot.get("flanges") or []
	if not segs:
		return ""
	start = snapshot.get("start") or {"x": 0, "y": 0}
	hem_left = bool(snapshot.get("hemLeft"))
	hem_right = bool(snapshot.get("hemRight"))
	hem_l_dir = snapshot.get("hemLeftDir", 1) or 1
	hem_r_dir = snapshot.get("hemRightDir", -1) or -1

	W, H = 336, 224
	v = _verts(start, segs)
	mnx = min(p["x"] for p in v)
	mxx = max(p["x"] for p in v)
	mny = min(p["y"] for p in v)
	mxy = max(p["y"] for p in v)
	cx, cy = (mnx + mxx) / 2, (mny + mxy) / 2
	bw, bh = max(1, mxx - mnx), max(1, mxy - mny)
	pad = 66
	k = min((W - pad) / bw, (H - pad) / bh)

	def D(p):
		return {"x": (p["x"] - cx) * k + W / 2, "y": (cy - p["y"]) * k + H / 2}

	d = [D(p) for p in v]
	parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" width="168" height="112">']

	# контур монохромной линией
	path = "M " + _fnum(d[0]["x"]) + " " + _fnum(d[0]["y"])
	for i in range(1, len(d)):
		path += f' L {_fnum(d[i]["x"])} {_fnum(d[i]["y"])}'
	parts.append(f'<path d="{path}" fill="none" stroke="#111" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>')

	# завальцовки (полукруг в цвет контура)
	def hem(edge, u, flip):
		nx, ny = -u["y"] * flip, u["x"] * flip
		r, L = 4, 12
		sx, sy = edge["x"], edge["y"]
		bx, by = sx + nx * 2 * r, sy + ny * 2 * r
		ex, ey = bx + u["x"] * L, by + u["y"] * L
		kk = r * 4 / 3
		c1x, c1y = sx - u["x"] * kk, sy - u["y"] * kk
		c2x, c2y = bx - u["x"] * kk, by - u["y"] * kk
		dd = f'M {_fnum(sx)} {_fnum(sy)} C {_fnum(c1x)} {_fnum(c1y)} {_fnum(c2x)} {_fnum(c2y)} {_fnum(bx)} {_fnum(by)} L {_fnum(ex)} {_fnum(ey)}'
		parts.append(f'<path d="{dd}" fill="none" stroke="#111" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')

	def unit(a, b):
		dx, dy = b["x"] - a["x"], b["y"] - a["y"]
		l = math.hypot(dx, dy) or 1
		return {"x": dx / l, "y": dy / l}

	if hem_left and len(d) >= 2:
		hem(d[0], unit(d[0], d[1]), hem_l_dir)
	if hem_right and len(d) >= 2:
		hem(d[-1], unit(d[-1], d[-2]), hem_r_dir)

	# подписи длин полок
	for i in range(len(segs)):
		a, b = d[i], d[i + 1]
		mx, my = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
		nx, ny = -(b["y"] - a["y"]), (b["x"] - a["x"])
		nl = math.hypot(nx, ny) or 1
		tx, ty = mx + nx / nl * 12, my + ny / nl * 12 + 3.5
		parts.append(f'<text x="{_fnum(tx)}" y="{_fnum(ty)}" text-anchor="middle" font-size="11" font-weight="700" fill="#111">{int(round(segs[i]["len"]))}</text>')

	# углы между полками (выносим наружу по биссектрисе)
	for i in range(1, len(segs)):
		if abs(_bend(segs, i)) < 1:
			continue
		p, a, b = d[i], d[i - 1], d[i + 1]
		t1x, t1y = a["x"] - p["x"], a["y"] - p["y"]
		l1 = math.hypot(t1x, t1y) or 1
		t1x, t1y = t1x / l1, t1y / l1
		t2x, t2y = b["x"] - p["x"], b["y"] - p["y"]
		l2 = math.hypot(t2x, t2y) or 1
		t2x, t2y = t2x / l2, t2y / l2
		bx, by = t1x + t2x, t1y + t2y
		bl = math.hypot(bx, by)
		if bl < 0.15:
			ox, oy = -t2y, t2x
		else:
			ox, oy = -bx / bl, -by / bl
		lx, ly = p["x"] + ox * 16, p["y"] + oy * 16 + 3.5
		parts.append(f'<text x="{_fnum(lx)}" y="{_fnum(ly)}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#111">{int(round(_flange(segs, i)))}°</text>')

	parts.append("</svg>")
	return "".join(parts)


# ---------------- расчёт позиции (через compute) ----------------

def item_numbers(snapshot, thickness, plank_length, qty):
	"""Числа позиции — через серверный compute (тот же, что calc/конструктор)."""
	segs = snapshot.get("segs") or snapshot.get("flanges") or []
	hem_len = float(snapshot.get("hemLen") or 0)
	res = compute(segs, bool(snapshot.get("hemLeft")), bool(snapshot.get("hemRight")),
	              hem_len, mass_per_sqm(thickness), plank_length, qty or 1)
	res["flanges_count"] = len(segs)
	return res


# ---------------- HTML листа (А4, ч/б) ----------------

_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:"DejaVu Sans",Arial,sans-serif;color:#111;font-size:12px}
.head{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #111;padding-bottom:12px;margin-bottom:8px}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:46px;height:46px;border-radius:9px;background:#111;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px;text-align:center;line-height:1.05}
.brand h1{margin:0;font-size:16px}
.brand .co{font-size:11px;color:#444;margin-top:2px}
.head .meta{text-align:right;font-size:11.5px;color:#444;line-height:1.7}
.head .meta b{color:#111;font-size:12.5px}
.order-tag{display:inline-block;background:#eee;color:#111;font-weight:700;border-radius:6px;padding:1px 8px}
.subhead{display:flex;justify-content:space-between;font-size:11.5px;color:#444;margin:8px 0 12px}
.subhead span{color:#111;font-weight:600}
.grid{display:flex;flex-wrap:wrap;gap:10px}
.card{border:1px solid #999;border-radius:8px;overflow:hidden;width:48%;break-inside:avoid;page-break-inside:avoid}
.card-head{display:flex;align-items:center;gap:8px;background:#f0f0f0;border-bottom:1px solid #999;padding:6px 9px}
.pos-num{width:21px;height:21px;border-radius:6px;background:#111;color:#fff;font-weight:700;font-size:11px;display:flex;align-items:center;justify-content:center}
.card-head .name{font-weight:700;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-body{display:flex;gap:8px;padding:8px 9px}
.sketch-box{width:170px;flex-shrink:0;border:1px solid #ddd;border-radius:6px;background:#fff;display:flex;align-items:center;justify-content:center}
.specs{flex:1;font-size:10.5px}
.specs table{width:100%;border-collapse:collapse}
.specs td{padding:1px 0;vertical-align:top}
.specs td.k{color:#555;white-space:nowrap;padding-right:6px}
.specs td.v{color:#111;font-weight:600;text-align:right}
.specs .dev{font-weight:800;font-size:12px}
.specs .strong td{border-top:1px dashed #999;padding-top:3px}
.totals{margin-top:14px;border-top:2px solid #111;padding-top:9px;display:flex;justify-content:space-between;font-size:12px}
.totals .tcell{color:#555}
.totals .tcell b{color:#111;font-size:13.5px;display:block;margin-top:2px}
.sheets{margin-top:12px}
.sheets-title{font-size:11px;font-weight:700;margin-bottom:5px}
.sheets-table{width:100%;border-collapse:collapse;font-size:11px}
.sheets-table th{text-align:left;background:#f0f0f0;border:1px solid #999;padding:4px 8px;font-weight:700}
.sheets-table td{border:1px solid #999;padding:4px 8px}
.sheets-table td.n,.sheets-table th.n{text-align:right}
.sheets-table tfoot td{font-weight:800;background:#f6f6f6}
.signs{margin-top:18px;display:flex;gap:36px;font-size:11px;color:#555}
.signs .sign{flex:1}
.signs .sline{margin-top:22px;border-bottom:1px solid #999}
.signs .scap{font-size:10px;color:#777;margin-top:3px}
.foot{margin-top:14px;display:flex;justify-content:space-between;font-size:10px;color:#777;border-top:1px solid #ddd;padding-top:6px}
@page{size:A4;margin:12mm}
"""


def _card_html(idx, item):
	snap = {}
	if item.get("profile_snapshot_json"):
		try:
			snap = json.loads(item["profile_snapshot_json"])
		except Exception:
			snap = {}
	thickness = float(item.get("thickness") or 0)
	plank = float(item.get("plank_length") or 2500)
	qty = int(item.get("qty") or 0)
	r = item_numbers(snap, thickness, plank, qty) if snap.get("segs") else None
	svg = sketch_svg(snap) if snap.get("segs") else '<div style="color:#999;font-size:10px;padding:20px">нет эскиза</div>'
	coating = escape(str(item.get("coating") or "—"))
	name = escape(str(item.get("title") or "Доборка"))
	lock = " 🤝" if snap.get("lockOn") else ""
	hem_len = snap.get("hemLen") or 15
	hem = f"{hem_len:g} мм" if (snap.get("hemLeft") or snap.get("hemRight")) else "—"
	if r:
		dev = f'{r["developed_width"]:g}'
		nflange = r["flanges_count"]
		nbend = r["bends"]
		w1 = f'{r["weight_one"]:.2f}'
		wall = f'{r["weight_total"]:.1f}'
	else:
		dev, nflange, nbend, w1, wall = "—", "—", "—", "—", "—"
	return f"""<div class="card">
	<div class="card-head"><span class="pos-num">{idx}</span><span class="name">{name}{lock}</span></div>
	<div class="card-body">
		<div class="sketch-box">{svg}</div>
		<div class="specs"><table>
			<tr><td class="k">Развёртка</td><td class="v dev">{dev} мм</td></tr>
			<tr><td class="k">Полок</td><td class="v">{nflange}</td></tr>
			<tr><td class="k">Гибов</td><td class="v">{nbend}</td></tr>
			<tr><td class="k">Толщина</td><td class="v">{thickness:g} мм</td></tr>
			<tr><td class="k">Покрытие</td><td class="v">{coating}</td></tr>
			<tr><td class="k">Длина планки</td><td class="v">{plank:g} мм</td></tr>
			<tr><td class="k">Завальцовка</td><td class="v">{hem}</td></tr>
			<tr class="strong"><td class="k">Количество</td><td class="v">{qty} шт</td></tr>
			<tr><td class="k">Вес 1 / всего</td><td class="v">{w1} / {wall} кг</td></tr>
		</table></div>
	</div>
</div>"""


def order_html(order):
	"""Полный HTML производственного листа по Dobor Order (документ или dict)."""
	if hasattr(order, "as_dict"):
		name = order.name
		customer = order.customer or "—"
		order_date = frappe.utils.formatdate(order.order_date) if order.order_date else ""
		items = [{
			"title": it.title, "coating": it.coating, "thickness": it.thickness,
			"plank_length": it.plank_length, "qty": it.qty,
			"profile_snapshot_json": it.profile_snapshot_json,
		} for it in order.items]
	else:
		name = order.get("name", "")
		customer = order.get("customer") or "—"
		order_date = order.get("order_date") or ""
		items = order.get("items") or []

	cards = "".join(_card_html(i + 1, it) for i, it in enumerate(items))

	# итоги + группировка расхода металла
	sum_qty = sum_area = sum_weight = 0.0
	groups = {}
	for it in items:
		snap = {}
		try:
			snap = json.loads(it.get("profile_snapshot_json") or "{}")
		except Exception:
			snap = {}
		if not snap.get("segs"):
			continue
		thickness = float(it.get("thickness") or 0)
		qty = int(it.get("qty") or 0)
		r = item_numbers(snap, thickness, float(it.get("plank_length") or 2500), qty)
		sum_qty += qty
		sum_area += r["area_one"] * qty
		sum_weight += r["weight_total"]
		gk = (thickness, str(it.get("coating") or "—"))
		groups[gk] = groups.get(gk, 0.0) + r["area_one"] * qty

	rows = ""
	tot_sheets = 0
	tot_area = 0.0
	for (th, col), area in sorted(groups.items()):
		sheets = math.ceil(area / SHEET_AREA) if area > 0 else 0
		tot_sheets += sheets
		tot_area += area
		rows += f'<tr><td>{th:g}</td><td>{escape(col)}</td><td class="n">{area:.2f}</td><td class="n">{sheets}</td></tr>'

	return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><style>{_CSS}</style></head><body>
	<div class="head">
		<div class="brand"><div class="logo">ПМК<br>ПАРК</div>
			<div><h1>Производственный лист — доборные элементы</h1>
			<div class="co">ООО «ПМК Парк» · завод металлоконструкций</div></div></div>
		<div class="meta">Заказ <span class="order-tag">{escape(name)}</span><br>Дата: <b>{escape(order_date)}</b><br>Позиций: <b>{len(items)}</b></div>
	</div>
	<div class="subhead"><div>Заказчик: <span>{escape(str(customer))}</span></div>
		<div>Составил: <span>{escape(frappe.session.user)}</span> · Принял в работу: ___________</div></div>
	<div class="grid">{cards}</div>
	<div class="totals">
		<div class="tcell">Позиций<b>{len(items)}</b></div>
		<div class="tcell">Всего планок, шт<b>{int(sum_qty)}</b></div>
		<div class="tcell">Площадь металла, м²<b>{sum_area:.2f}</b></div>
		<div class="tcell">Общий вес, кг<b>{sum_weight:.1f}</b></div>
	</div>
	<div class="sheets"><div class="sheets-title">Расход металла (лист {SHEET_W_MM} × {SHEET_L_MM} мм, ориентировочно по площади)</div>
		<table class="sheets-table"><thead><tr><th>Толщина, мм</th><th>Цвет / покрытие</th><th class="n">Площадь, м²</th><th class="n">Листов, шт</th></tr></thead>
		<tbody>{rows}</tbody>
		<tfoot><tr><td colspan="2">Итого</td><td class="n">{tot_area:.2f}</td><td class="n">{tot_sheets}</td></tr></tfoot></table></div>
	<div class="signs">
		<div class="sign"><div class="sline"></div><div class="scap">Гибщик (ФИО / подпись)</div></div>
		<div class="sign"><div class="sline"></div><div class="scap">ОТК (ФИО / подпись)</div></div>
		<div class="sign"><div class="sline"></div><div class="scap">Дата выполнения</div></div>
	</div>
	<div class="foot"><span>Развёртка = сумма полок + завальцовки (без поправки на гиб). Углы — между полками.</span><span>Factory Platform · ПМК Парк</span></div>
	</body></html>"""


@frappe.whitelist()
def render_pdf(order_name):
	"""Сгенерировать производственный лист (PDF) по заказу доборок и отдать на скачивание."""
	from frappe.utils.pdf import get_pdf

	doc = frappe.get_doc("Dobor Order", order_name)
	html = order_html(doc)
	pdf = get_pdf(html, options={"page-size": "A4", "encoding": "UTF-8",
	                             "margin-top": "12mm", "margin-bottom": "12mm",
	                             "margin-left": "12mm", "margin-right": "12mm"})
	frappe.local.response.filename = f"{order_name}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"
