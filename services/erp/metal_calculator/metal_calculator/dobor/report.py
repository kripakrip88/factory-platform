# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Производственный лист доборных элементов (PDF).

Вёрстка по утверждённому макету: 1 столбец × 3 доборки на лист, крупный эскиз
сечения (с пунктиром стороны покрытия), инфо-блок с разделителями, итоги,
расход металла. ТАБЛИЧНАЯ вёрстка — wkhtmltopdf не поддерживает flex/grid.

Эскизы рисуются server-side из profile_snapshot_json (порт прототипа). Числа —
через compute() (единый источник истины с конструктором и calc). Документ ч/б.
"""

import json
import math
from html import escape

import frappe

from metal_calculator.dobor.api import compute, mass_per_sqm

SHEET_W_MM = 1250  # лист по умолчанию
SHEET_L_MM = 2500
SHEET_AREA = (SHEET_W_MM / 1000.0) * (SHEET_L_MM / 1000.0)  # м²


def _logo_svg():
	"""Логотип ПМК Парк — 6 полосок, сходящихся к центру (как на лого). Высота ≤44px."""
	cx, cy, R = 20, 20, 16
	arms = []
	for ang in range(0, 360, 60):
		r = math.radians(ang)
		arms.append(f'<line x1="{cx}" y1="{cy}" x2="{cx + R * math.cos(r):.1f}" y2="{cy + R * math.sin(r):.1f}"/>')
	return ('<svg viewBox="0 0 40 40" width="44" height="44" xmlns="http://www.w3.org/2000/svg">'
	        f'<g stroke="#111" stroke-width="3.4" stroke-linecap="round">{"".join(arms)}</g></svg>')


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


def _n(x):
	return f"{x:.1f}"


def sketch_svg(snapshot):
	"""Крупный монохромный эскиз сечения (SVG-строка): контур, размеры, углы между
	полками, завальцовка полукругом, ПУНКТИР стороны покрытия."""
	segs = snapshot.get("segs") or snapshot.get("flanges") or []
	if not segs:
		return ""
	start = snapshot.get("start") or {"x": 0, "y": 0}
	hem_left = bool(snapshot.get("hemLeft"))
	hem_right = bool(snapshot.get("hemRight"))
	hem_l_dir = snapshot.get("hemLeftDir", 1) or 1
	hem_r_dir = snapshot.get("hemRightDir", -1) or -1
	paint_side = snapshot.get("paintSide", 1) or 1

	W, H = 470, 300
	v = _verts(start, segs)
	mnx = min(p["x"] for p in v)
	mxx = max(p["x"] for p in v)
	mny = min(p["y"] for p in v)
	mxy = max(p["y"] for p in v)
	cx, cy = (mnx + mxx) / 2, (mny + mxy) / 2
	bw, bh = max(1, mxx - mnx), max(1, mxy - mny)
	pad = 86  # поле под подписи (меньше — эскиз крупнее, заполняет карточку)
	k = min((W - pad) / bw, (H - pad) / bh)

	def D(p):
		# та же ориентация, что в конструкторе (без вертикального зеркала)
		return {"x": (p["x"] - cx) * k + W / 2, "y": (p["y"] - cy) * k + H / 2}

	d = [D(p) for p in v]

	def unit(a, b):
		dx, dy = b["x"] - a["x"], b["y"] - a["y"]
		l = math.hypot(dx, dy) or 1
		return {"x": dx / l, "y": dy / l}

	parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" width="100%" style="display:block">']

	# контур: подгиб 180° — параллельная линия + разворот «U». Смещение НАКОПИТЕЛЬНОЕ.
	# Все построения (контур, краска, подписи) — по СМЕЩЁННОМУ контуру (drawn), чтобы
	# при загибах подписи не «заплывали» и пунктир не вставал криво.
	GAP = 8
	isfold = lambda s: 1 <= s < len(segs) and abs(_bend(segs, s)) > 170
	shift = {"x": 0.0, "y": 0.0}

	def sh(i):
		return {"x": d[i]["x"] + shift["x"], "y": d[i]["y"] + shift["y"]}

	dpts = [sh(0)]            # точки смещённого контура (для краски)
	seglab = []               # (a, b) смещённые концы каждой полки — для подписей длин
	vout = [sh(0)]            # позиция вершины (исходящая) — для подписей углов
	path = "M " + _n(dpts[0]["x"]) + " " + _n(dpts[0]["y"])
	for s in range(len(segs)):
		a = sh(s)  # вход в вершину s
		if isfold(s):
			dr = unit(d[s], d[s + 1]); n = {"x": -dr["y"], "y": dr["x"]}
			side = (-1 if _bend(segs, s) > 0 else 1) * (-1 if segs[s].get("foldFlip") else 1)
			shift = {"x": shift["x"] + n["x"] * side * GAP, "y": shift["y"] + n["y"] * side * GAP}
			aoff = sh(s)  # выход из вершины s (после сдвига)
			uin = unit(d[s - 1], d[s])
			cross = (aoff["x"] - a["x"]) * uin["y"] - (aoff["y"] - a["y"]) * uin["x"]
			sweep = 0 if cross > 0 else 1
			b = sh(s + 1)
			path += f' A {GAP / 2} {GAP / 2} 0 0 {sweep} {_n(aoff["x"])} {_n(aoff["y"])} L {_n(b["x"])} {_n(b["y"])}'
			dpts.append(aoff); dpts.append(b)
			seglab.append((aoff, b)); vout[s] = aoff
		else:
			b = sh(s + 1)
			path += f' L {_n(b["x"])} {_n(b["y"])}'
			dpts.append(b); seglab.append((a, b)); vout[s] = a
		vout.append(b)
	parts.append(f'<path d="{path}" fill="none" stroke="#111" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>')

	# пунктир стороны покрытия (если включено) — по смещённому контуру
	if snapshot.get("paintOn"):
		pl = []
		for i in range(len(dpts)):
			nx = ny = 0.0
			if i < len(dpts) - 1:
				u = unit(dpts[i], dpts[i + 1]); nx += -u["y"]; ny += u["x"]
			if i > 0:
				u2 = unit(dpts[i - 1], dpts[i]); nx += -u2["y"]; ny += u2["x"]
			l = math.hypot(nx, ny) or 1
			pl.append(f'{_n(dpts[i]["x"] + nx / l * 7 * paint_side)},{_n(dpts[i]["y"] + ny / l * 7 * paint_side)}')
		parts.append(f'<polyline points="{" ".join(pl)}" fill="none" stroke="#888" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>')

	# завальцовки (полукруг) — по смещённым краям
	def hem(edge, u, flip):
		nx, ny = -u["y"] * flip, u["x"] * flip
		r, L = 5, 15
		sx, sy = edge["x"], edge["y"]
		bx, by = sx + nx * 2 * r, sy + ny * 2 * r
		ex, ey = bx + u["x"] * L, by + u["y"] * L
		kk = r * 4 / 3
		dd = f'M {_n(sx)} {_n(sy)} C {_n(sx - u["x"] * kk)} {_n(sy - u["y"] * kk)} {_n(bx - u["x"] * kk)} {_n(by - u["y"] * kk)} {_n(bx)} {_n(by)} L {_n(ex)} {_n(ey)}'
		parts.append(f'<path d="{dd}" fill="none" stroke="#111" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')

	if hem_left and len(segs) >= 1:
		hem(vout[0], unit(vout[0], vout[1]), hem_l_dir)
	if hem_right and len(segs) >= 1:
		hem(vout[len(segs)], unit(vout[len(segs)], vout[len(segs) - 1]), hem_r_dir)

	# подписи длин полок — по смещённому контуру
	for i in range(len(segs)):
		a, b = seglab[i]
		mx, my = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
		nx, ny = -(b["y"] - a["y"]), (b["x"] - a["x"])
		nl = math.hypot(nx, ny) or 1
		tx, ty = mx + nx / nl * 22, my + ny / nl * 22 + 5
		parts.append(f'<text x="{_n(tx)}" y="{_n(ty)}" text-anchor="middle" font-size="18" font-weight="700" fill="#111">{int(round(segs[i]["len"]))}</text>')

	# углы между полками (наружу по биссектрисе); на загибе 180° угол не подписываем
	for i in range(1, len(segs)):
		ba = abs(_bend(segs, i))
		if ba < 1 or ba > 170:
			continue
		p, a, b = vout[i], vout[i - 1], vout[i + 1]
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
		lx, ly = p["x"] + ox * 22, p["y"] + oy * 22 + 5
		parts.append(f'<text x="{_n(lx)}" y="{_n(ly)}" text-anchor="middle" font-size="16" font-weight="700" fill="#111">{int(round(_flange(segs, i)))}°</text>')

	parts.append("</svg>")
	return "".join(parts)


# ---------------- расчёт позиции (через compute) ----------------

def item_numbers(snapshot, thickness, plank_length, qty):
	"""Числа позиции — через серверный compute (тот же, что calc/конструктор)."""
	segs = snapshot.get("segs") or snapshot.get("flanges") or []
	hem_len = float(snapshot.get("hemLen") or 0)
	res = compute(segs, bool(snapshot.get("hemLeft")), bool(snapshot.get("hemRight")),
	              hem_len, mass_per_sqm(thickness), plank_length, qty or 1,
	              lock=bool(snapshot.get("lockOn")))
	res["flanges_count"] = len(segs)
	return res


# ---------------- HTML листа (А4, ч/б, табличная вёрстка) ----------------

_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:"DejaVu Sans",Arial,sans-serif;color:#111;font-size:12px;line-height:1.4}
.head{width:100%;border-collapse:collapse;border-bottom:2px solid #111;table-layout:fixed}
.logo{width:46px;height:46px;border-radius:9px;background:#f3f3f3;border:1px solid #ccc;color:#666;text-align:center;font-weight:800;font-size:12px;line-height:1.05}
.h1{font-size:15px;font-weight:700;line-height:1.2;white-space:nowrap}
.co{font-size:11px;color:#444;margin-top:2px}
.meta{text-align:right;font-size:11.5px;color:#444;line-height:1.7}
.meta b{color:#111}
.order-tag{display:inline-block;background:#eee;color:#111;font-weight:700;border-radius:6px;padding:1px 8px}
.subhead{width:100%;border-collapse:collapse;margin:9px 0 13px;font-size:11.5px;color:#444}
.subhead b{color:#111;font-weight:600}
.card{border:1px solid #999;border-radius:8px;overflow:hidden;margin-bottom:11px;page-break-inside:avoid}
.ch{width:100%;border-collapse:collapse;background:#f0f0f0;border-bottom:1px solid #999}
.pos-num{width:20px;height:20px;border:1px solid #aaa;border-radius:5px;color:#555;font-weight:700;font-size:11px;text-align:center;line-height:20px}
.chk{width:13px;height:13px;border:1.5px solid #888;border-radius:3px}
.cname{font-weight:700;font-size:12.5px}
.ccomment{font-size:11px;color:#333;font-style:italic;padding:5px 10px;border-bottom:1px solid #e6e6e6;background:#fafafa}
.lock{font-size:9.5px;font-weight:700;color:#111;border:1px solid #111;border-radius:4px;padding:1px 5px;margin-left:6px}
.cb{width:100%;border-collapse:collapse}
.specs{width:100%;border-collapse:collapse;font-size:11.5px}
.specs td{padding:3px 0;border-bottom:1px solid #e6e6e6}
.specs td.k{color:#555}
.specs td.v{text-align:right;font-weight:600}
.specs .dev{font-weight:800;font-size:13px}
.specs tr.strong td{border-top:1px solid #999;border-bottom:1px solid #e6e6e6}
.specs tr:last-child td{border-bottom:none}
.totals{width:100%;border-collapse:collapse;border-top:2px solid #111;margin-top:14px;page-break-inside:avoid}
.totals td{text-align:center;color:#555;font-size:12px;padding:9px 4px 0}
.totals td b{display:block;color:#111;font-size:14px;margin-top:2px}
.sheets-title{font-size:11px;font-weight:700;margin:13px 0 5px}
.sheets{width:100%;border-collapse:collapse;font-size:11px;border-radius:6px;overflow:hidden;page-break-inside:avoid}
.sheets th{text-align:left;background:#f0f0f0;border:1px solid #bbb;padding:5px 8px;font-weight:700}
.sheets td{border:1px solid #bbb;padding:5px 8px}
.sheets td.n,.sheets th.n{text-align:right}
.sheets tfoot td{font-weight:800;background:#f6f6f6}
.signs{width:100%;border-collapse:collapse;margin-top:20px;font-size:11px;color:#555}
.signs .sline{border-bottom:1px solid #999;height:26px}
.signs .scap{font-size:10px;color:#777;margin-top:3px}
.foot{width:100%;border-collapse:collapse;margin-top:14px;border-top:1px solid #ddd;font-size:10px;color:#777}
.foot td{padding-top:6px}
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
	svg = sketch_svg(snap) if snap.get("segs") else '<div style="color:#999;font-size:10px;padding:24px;text-align:center">нет эскиза</div>'
	coating = escape(str(item.get("coating") or "—"))
	name = escape(str(item.get("title") or "Доборка"))
	lock = '<span class="lock">ЗАМОК</span>' if snap.get("lockOn") else ""
	hem_len = snap.get("hemLen") or 15
	hem = f"{hem_len:g} мм" if (snap.get("hemLeft") or snap.get("hemRight")) else "—"
	if r:
		dev, nflange, nbend = f'{r["developed_width"]:g}', r["flanges_count"], r["bends"]
		w1, wall = f'{r["weight_one"]:.2f}', f'{r["weight_total"]:.1f}'
	else:
		dev, nflange, nbend, w1, wall = "—", "—", "—", "—", "—"
	comment = (snap.get("comment") or "").strip()
	comment_bar = f'<div class="ccomment">{escape(comment)}</div>' if comment else ""
	return f"""<div class="card">
	<table class="ch"><tr>
		<td style="width:24px;padding:6px 0 6px 9px"><div class="pos-num">{idx}</div></td>
		<td style="width:18px;padding:6px 6px"><div class="chk"></div></td>
		<td style="padding:6px 9px 6px 0"><span class="cname">{name}</span>{lock}</td>
	</tr></table>
	{comment_bar}
	<table class="cb"><tr>
		<td style="width:68%;padding:6px 2px 6px 6px;vertical-align:middle">{svg}</td>
		<td style="width:32%;padding:8px 9px 8px 4px;vertical-align:top">
		<table class="specs">
			<tr><td class="k">Развёртка</td><td class="v dev">{dev} мм</td></tr>
			<tr><td class="k">Полок / гибов</td><td class="v">{nflange} / {nbend}</td></tr>
			<tr><td class="k">Толщина</td><td class="v">{thickness:g} мм</td></tr>
			<tr><td class="k">Покрытие</td><td class="v" style="white-space:nowrap">{coating}</td></tr>
			<tr><td class="k">Длина планки</td><td class="v">{plank:g} мм</td></tr>
			<tr><td class="k">Завальцовка</td><td class="v">{hem}</td></tr>
			<tr class="strong"><td class="k">Количество</td><td class="v">{qty} шт</td></tr>
			<tr><td class="k">Вес 1 / всего</td><td class="v">{w1} / {wall} кг</td></tr>
		</table></td>
	</tr></table>
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
	sum_bends = 0
	groups = {}
	for it in items:
		try:
			snap = json.loads(it.get("profile_snapshot_json") or "{}")
		except Exception:
			snap = {}
		if not snap.get("segs"):
			continue
		thickness = float(it.get("thickness") or 0)
		qty = int(it.get("qty") or 0)
		plank = float(it.get("plank_length") or 2500)
		r = item_numbers(snap, thickness, plank, qty)
		sum_qty += qty
		sum_area += r["area_one"] * qty
		sum_weight += r["weight_total"]
		sum_bends += r["bends"] * qty  # всего гибов по заказу (на все планки)
		gk = (thickness, str(it.get("coating") or "—"))
		groups[gk] = groups.get(gk, 0.0) + r["area_one"] * qty

	srows = ""
	tot_sheets = 0
	tot_area = 0.0
	for (th, col), area in sorted(groups.items()):
		sheets = math.ceil(area / SHEET_AREA) if area > 0 else 0
		tot_sheets += sheets
		tot_area += area
		srows += f'<tr><td>{th:g}</td><td>{escape(col)}</td><td class="n">{area:.2f}</td><td class="n">{sheets}</td></tr>'

	def tcell(lbl, val):
		return f'<td>{lbl}<b>{val}</b></td>'

	totals = (tcell("Позиций", len(items)) + tcell("Гибов всего", sum_bends)
	          + tcell("Всего планок, шт", int(sum_qty)) + tcell("Площадь металла, м²", f"{sum_area:.2f}")
	          + tcell("Общий вес, кг", f"{sum_weight:.1f}"))

	return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><style>{_CSS}</style></head><body>
	<table class="head"><tr>
		<td style="width:70%;vertical-align:middle;padding-bottom:12px"><table><tr>
			<td style="width:50px;vertical-align:middle">{_logo_svg()}</td>
			<td style="padding-left:12px;vertical-align:middle"><div class="h1">Производственный лист на доборные элементы</div><div class="co">ООО «ПМК Парк» · завод металлоконструкций · <a href="https://pmkpark.ru/" style="color:#111;text-decoration:underline">pmkpark.ru</a></div></td>
		</tr></table></td>
		<td style="width:30%;vertical-align:top;padding-bottom:12px"><table style="margin-left:auto;border-collapse:collapse;font-size:11.5px;color:#444;white-space:nowrap">
			<tr><td style="text-align:right;padding:0 6px 3px 0">Заказ</td><td style="text-align:right;padding-bottom:3px"><span class="order-tag">{escape(name)}</span></td></tr>
			<tr><td style="text-align:right;padding-right:6px">Дата</td><td style="text-align:right"><b style="color:#111">{escape(order_date)}</b></td></tr>
			<tr><td style="text-align:right;padding-right:6px">Позиций</td><td style="text-align:right"><b style="color:#111">{len(items)}</b></td></tr>
		</table></td>
	</tr></table>
	<table class="subhead"><tr>
		<td>Заказчик: <b>{escape(str(customer))}</b></td>
		<td style="text-align:right">Составил: <b>{escape(frappe.session.user)}</b> · Принял в работу: ___________</td>
	</tr></table>
	{cards}
	<table class="totals"><tr>{totals}</tr></table>
	<div class="sheets-title">Расход металла (лист {SHEET_W_MM} × {SHEET_L_MM} мм, ориентировочно по площади)</div>
	<table class="sheets"><thead><tr><th>Толщина, мм</th><th>Цвет / покрытие</th><th class="n">Площадь, м²</th><th class="n">Листов, шт</th></tr></thead>
		<tbody>{srows}</tbody>
		<tfoot><tr><td colspan="2">Итого</td><td class="n">{tot_area:.2f}</td><td class="n">{tot_sheets}</td></tr></tfoot></table>
	<table class="signs"><tr>
		<td style="width:33%"><div class="sline"></div><div class="scap">Гибщик (ФИО / подпись)</div></td>
		<td style="width:6%"></td>
		<td style="width:33%"><div class="sline"></div><div class="scap">ОТК (ФИО / подпись)</div></td>
		<td style="width:6%"></td>
		<td style="width:22%"><div class="sline"></div><div class="scap">Дата выполнения</div></td>
	</tr></table>
	<table class="foot"><tr>
		<td>Развёртка = сумма полок + завальцовки (без поправки на гиб). Углы — между полками. Пунктир — сторона покрытия.</td>
		<td style="text-align:right">Factory Platform · ПМК Парк</td>
	</tr></table>
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
