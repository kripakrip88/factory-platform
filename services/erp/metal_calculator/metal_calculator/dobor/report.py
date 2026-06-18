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
