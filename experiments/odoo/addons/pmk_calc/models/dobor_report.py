# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Производственный лист доборных элементов.

ПЕРЕНОС С ERPNEXT. Вёрстка и генератор эскиза оставлены ДОСЛОВНО: лист уже
выверен на печати, а таблицы выбраны не от бедности — wkhtmltopdf не понимает
flex и grid, и на них карточки схлопываются в один столбец. Odoo печатает тем
же wkhtmltopdf, поэтому менять было нечего.

Заменено только обращение к фреймворку: расчёт берётся из compute_dobor
(общая функция с формой позиции), автор листа приходит параметром, а PDF
собирает штатный отчёт Odoo вместо frappe.utils.pdf.

Оригинал: services/erp/metal_calculator/metal_calculator/dobor/report.py

Макет: 1 столбец × 3 доборки на лист, крупный эскиз сечения с пунктиром
стороны покрытия, инфо-блок с разделителями, итоги, расход металла. Ч/б.
"""

import json
import math
from html import escape

from .dobor import compute_dobor, normalize_hex

SHEET_W_MM = 1250  # лист по умолчанию
SHEET_L_MM = 2500
SHEET_AREA = (SHEET_W_MM / 1000.0) * (SHEET_L_MM / 1000.0)  # м²

# Полоса внизу эскиза под знак замка — резервируется ТОЛЬКО когда замок есть.
# Высота подобрана по плашке 76×44 плюс воздух сверху и снизу.
LOCK_BAND = 64


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


# Пунктир покрытия, когда покрытие у позиции не выбрано. Это не цвет краски,
# а признак «цвет не выбран», поэтому с запасным цветом холста построителя
# (там он розовый) совпадать не обязан — совпадать должны настоящие цвета.
NO_COATING_STROKE = "#888"


def _darken(hex_color, factor=0.62):
	"""Притушить цвет покрытия для печати.

	Лист печатают на белом, и светлое покрытие тонким пунктиром на белом не
	читается: RAL 9003 «Белый» — #f1f0ea. Множитель 0.62 взят из построителя
	ERPNext, там он стоял ровно на обводке слоя краски.

	Разбор — общей функцией dobor.normalize_hex, а не своей проверкой: цвет
	читает ещё и живой холст построителя, и пока правил было два, значение без
	решётки красило печать и не красило экран. Где живёт единственное правило и
	почему — описано в docstring normalize_hex. Возвращает None на всём, что не
	похоже на #rrggbb: в снимок цвет попадает из справочника, а тот правят
	руками, и мусор в поле не должен ронять эскиз.
	"""
	m = normalize_hex(hex_color)
	if not m:
		return None
	rgb = [int(m[i:i + 2], 16) for i in (1, 3, 5)]
	return "#" + "".join("%02x" % max(0, min(255, round(c * factor))) for c in rgb)


def sketch_svg(snapshot):
	"""Крупный монохромный эскиз сечения (SVG-строка): контур, размеры, углы между
	полками, завальцовка полукругом, ПУНКТИР стороны покрытия, знак замка."""
	segs = snapshot.get("segs") or snapshot.get("flanges") or []
	if not segs:
		return ""
	start = snapshot.get("start") or {"x": 0, "y": 0}
	hem_left = bool(snapshot.get("hemLeft"))
	hem_right = bool(snapshot.get("hemRight"))
	hem_l_dir = snapshot.get("hemLeftDir", 1) or 1
	hem_r_dir = snapshot.get("hemRightDir", -1) or -1
	paint_side = snapshot.get("paintSide", 1) or 1
	# Цвет слоя краски лежит В СНИМКЕ (paintHex) — его туда вписывает
	# DoborOrderLine._sync_snapshot_coating при сохранении позиции. Справочник
	# покрытий отсюда НЕ читаем намеренно: там правят RAL, и чтение задним
	# числом перекрашивало бы эскизы в уже отпечатанных заказах.
	paint_stroke = _darken(snapshot.get("paintHex")) or NO_COATING_STROKE
	# Построитель Odoo пишет в снимок ключ `lock`, построитель ERPNext писал
	# `lockOn` (metal_calculator/page/dobor_builder/dobor_builder.js, функция
	# snapshot()). Читаем оба ключа — так же, как item_numbers ниже.
	# На стенде снимков с `lockOn` НЕТ ни одного (проверено запросом по
	# pmk_dobor_order_line). Чтение второго ключа — не описание сегодняшних
	# данных, а страховка на перенос заказов из ERPNext.
	lock = bool(snapshot.get("lock") or snapshot.get("lockOn"))

	W, H = 470, 300
	# Замок — не элемент сечения, а способ стыковки планок, на контуре его не
	# нарисовать. Живой холст кладёт знак в фиксированную зону снизу по центру
	# (dobor_builder.js: cy = VIEW_H - 68) — здесь то же место. Но холст может
	# не освобождать низ: там масштаб зажат k<=1.8 и контур почти всегда мелкий,
	# а эскиз вписывается в карточку без потолка и растягивается на всю высоту.
	# Проверено на снимке строки 18 (полки 61 и 85): без резерва контур доходит
	# до y=257 и подпись нижней полки ложится прямо на знак. Поэтому при замке
	# низ отдаётся знаку, а контур вписывается в оставшуюся высоту.
	#
	# Запас резерва съедает подгиб 180°: вписывание считается по ИСХОДНЫМ
	# вершинам и ничего не знает про накопительное смещение GAP, которым
	# рисуется подгиб, — нарисованный контур всегда ниже расчётного. Замер на
	# полках 120/60/90: без подгиба (направления 0/90/0) контур занимает
	# y 95..205, с подгибом (0/180/90) — y 51..265 при высоте холста 300. Поле
	# pad это пока перекрывает, за холст ни один проверенный профиль не вышел.
	# Это отдельная болячка вписывания, замок её не создаёт и не чинит.
	band = LOCK_BAND if lock else 0
	area_h = H - band
	v = _verts(start, segs)
	mnx = min(p["x"] for p in v)
	mxx = max(p["x"] for p in v)
	mny = min(p["y"] for p in v)
	mxy = max(p["y"] for p in v)
	cx, cy = (mnx + mxx) / 2, (mny + mxy) / 2
	bw, bh = max(1, mxx - mnx), max(1, mxy - mny)
	pad = 86  # поле под подписи (меньше — эскиз крупнее, заполняет карточку)
	k = min((W - pad) / bw, (area_h - pad) / bh)

	def D(p):
		# та же ориентация, что в конструкторе (без вертикального зеркала);
		# по вертикали центрируем по ОСТАВШЕЙСЯ площади, а не по всему холсту —
		# иначе резерв под замок съедался бы с обеих сторон и смысла не имел
		return {"x": (p["x"] - cx) * k + W / 2, "y": (p["y"] - cy) * k + area_h / 2}

	d = [D(p) for p in v]

	def unit(a, b):
		dx, dy = b["x"] - a["x"], b["y"] - a["y"]
		l = math.hypot(dx, dy) or 1
		return {"x": dx / l, "y": dy / l}

	# Эскиз рисуется тёмным по белому — таким он уходит в печать. В списке
	# позиций тот же SVG показывается в тёмном интерфейсе, и до сих пор его
	# выворачивал CSS-фильтр (scss, `.pmk-sketch svg`: invert(1) brightness(1.6)).
	# С цветным пунктиром покрытия так больше нельзя: инверсия меняет тон —
	# шоколадный RAL 8017 (#3a2419) стал бы голубым. Поэтому эскиз несёт свой
	# белый лист и отключает фильтр инлайновым стилем: инлайн сильнее правила
	# таблицы стилей, !important в том правиле нет. Сам фильтр в scss трогать
	# нельзя — тот же виджет и тот же класс использует эскиз раскроя в
	# pmk_laser, а он одноцветный, и выворачивание ему как раз нужно.
	parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" width="100%" '
	         'style="display:block;filter:none;opacity:1">',
	         f'<rect x="0" y="0" width="{W}" height="{H}" rx="10" fill="#ffffff"/>']

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
		parts.append(f'<polyline points="{" ".join(pl)}" fill="none" stroke="{paint_stroke}" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>')

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

	# Замок — «рукопожатие» на белой плашке снизу по центру: тот же знак и то же
	# место, что на живом холсте (dobor_builder.js, блок замка в redraw(); на
	# номера строк не ссылаемся — блок переезжает), только крупнее
	# относительно холста: эскиз мельче построителя (470×300 против 760×440),
	# и пропорциональный порт дал бы плашку 32×30 — в списке это 6×5 px.
	#
	# Подпись «ЗАМОК» из холста здесь НЕ повторяем. В списке позиций эскиз
	# показывается в 120×56 px (scss .pmk-sketch), viewBox 470×300 ужимается до
	# k≈0.19 — шрифт 9 превратился бы в 1.7 px, то есть в грязное пятно (там уже
	# и подписи полок, 18 px, читаются как 3.4 px). Плашка со знаком на таком
	# масштабе даёт 14×8 px и различается хотя бы силуэтом, а слово стоит
	# текстовой плашкой у названия позиции в печатном листе (_card_html) —
	# картинке его дублировать незачем. Слово всё же положено в <title>: по
	# спецификации SVG это не рисуемый элемент, а подсказка, то есть в печать
	# не попадёт; расчёт на то, что в списке браузер покажет её при наведении
	# (живьём не проверяли — стенд не трогали).
	if lock:
		bx, by = W / 2, H - band / 2
		parts.append(f'<rect x="{_n(bx - 38)}" y="{_n(by - 22)}" width="76" height="44" rx="9" '
		             'fill="#ffffff" stroke="#111" stroke-width="2"/>')
		# Знак нарисован в координатах холста (x -20..20), поэтому масштабируем
		# группой; сдвиг на 2 вверх — оптическое центрирование, ладони в
		# исходном знаке лежат ниже середины.
		parts.append(f'<g transform="translate({_n(bx)},{_n(by - 2)}) scale(1.5)" stroke="#111" '
		             'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none">'
		             '<title>Замок</title>')
		for dd in ("M -20 7 L -8 -3", "M 20 7 L 8 -3",
		           "M -3 0 l 3 5", "M 1 -1 l 3 5", "M 5 -2 l 2 5"):
			parts.append(f'<path d="{dd}"/>')
		# Сомкнутые ладони — линия потолще, в мелком масштабе она несёт весь смысл.
		parts.append('<path d="M -8 -3 Q -1 2 3 -1 Q 7 -4 9 -2" stroke-width="2.6"/></g>')

	parts.append("</svg>")
	return "".join(parts)


# ---------------- расчёт позиции (через compute) ----------------

def item_numbers(snapshot, thickness, plank_length, qty, mass_per_sqm):
	"""Числа позиции — той же функцией, что считает форму позиции.

	Массу 1 м² передаём снаружи: этот модуль намеренно не ходит в базу,
	иначе его нельзя проверить без запущенной Odoo.
	"""
	segs = snapshot.get("segs") or snapshot.get("flanges") or []
	hem_len = float(snapshot.get("hemLen") or 0)
	res = compute_dobor(segs, bool(snapshot.get("hemLeft")), bool(snapshot.get("hemRight")),
	                    hem_len, mass_per_sqm, plank_length, qty or 1,
	                    lock=bool(snapshot.get("lockOn") or snapshot.get("lock")))
	res["flanges_count"] = len(segs)
	return res


# ---------------- HTML листа (А4, ч/б, табличная вёрстка) ----------------

_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:"DejaVu Sans",Arial,sans-serif;color:#111;font-size:12px;line-height:1.4}
.head{width:100%;border-collapse:collapse;border-bottom:2px solid #111;table-layout:fixed}
.logo{width:46px;height:46px;border-radius:9px;background:#111;color:#fff;text-align:center;font-weight:800;font-size:12px;line-height:1.05}
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


def _card_html(idx, item, mps_for_thickness):
	snap = {}
	if item.get("profile_snapshot_json"):
		try:
			snap = json.loads(item["profile_snapshot_json"])
		except Exception:
			snap = {}
		# Старый формат снимка — голый список полок, без ключей. Дальше по коду
		# идут snap.get(...), и на списке это AttributeError: печать всего
		# заказа падала целиком из-за одной такой позиции.
		if isinstance(snap, list):
			snap = {"segs": snap}
		elif not isinstance(snap, dict):
			snap = {}
	thickness = float(item.get("thickness") or 0)
	plank = float(item.get("plank_length") or 2500)
	qty = int(item.get("qty") or 0)
	r = item_numbers(snap, thickness, plank, qty, mps_for_thickness(thickness)) if snap.get("segs") else None
	svg = sketch_svg(snap) if snap.get("segs") else '<div style="color:#999;font-size:10px;padding:24px;text-align:center">нет эскиза</div>'
	coating = escape(str(item.get("coating") or "—"))
	name = escape(str(item.get("title") or "Доборка"))
	# Построитель пишет в снимок ключ `lock`, а `lockOn` — наследие ERPNext.
	# Читали только второй, поэтому на профилях, нарисованных в Odoo, плашка
	# ЗАМОК не печаталась НИКОГДА, хотя замок даёт два гиба из расчёта.
	# item_numbers уже читает оба ключа — здесь было расхождение с ним.
	#
	# Плашку оставляем, хотя на эскизе теперь есть знак: это разные каналы, а не
	# дубль. Плашка — слово в шапке карточки, её видно при беглом просмотре
	# листа и по ней ищут глазами; знак стоит на чертеже, где гибщик смотрит
	# геометрию. Подписи «ЗАМОК» на самом эскизе нет (см. sketch_svg), так что
	# одно и то же слово дважды рядом не печатается.
	lock = '<span class="lock">ЗАМОК</span>' if (snap.get("lockOn") or snap.get("lock")) else ""
	# Было `or 15`: при завальцовке без длины лист печатал «15 мм», а в расчёт
	# (строка 204) шёл ноль. Цех гнул по одному числу, считали по другому.
	hem_len = float(snap.get("hemLen") or 0)
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


def order_html(order, mps_for_thickness, author=""):
	"""Полный HTML производственного листа по Dobor Order (документ или dict)."""
	if True:
		name = order.get("name", "")
		customer = order.get("customer") or "—"
		order_date = order.get("order_date") or ""
		items = order.get("items") or []

	cards = "".join(_card_html(i + 1, it, mps_for_thickness) for i, it in enumerate(items))

	# итоги + группировка расхода металла
	sum_qty = sum_area = sum_weight = 0.0
	sum_bends = 0
	groups = {}
	for it in items:
		try:
			snap = json.loads(it.get("profile_snapshot_json") or "{}")
		except Exception:
			snap = {}
		if isinstance(snap, list):
			snap = {"segs": snap}
		elif not isinstance(snap, dict):
			snap = {}
		if not snap.get("segs"):
			continue
		thickness = float(it.get("thickness") or 0)
		qty = int(it.get("qty") or 0)
		plank = float(it.get("plank_length") or 2500)
		r = item_numbers(snap, thickness, plank, qty, mps_for_thickness(thickness))
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
			<td style="width:50px;vertical-align:middle"><div class="logo"><span style="display:inline-block;line-height:46px"><span style="display:inline-block;line-height:1.05;vertical-align:middle">ПМК<br>ПАРК</span></span></div></td>
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
		<td style="text-align:right">Составил: <b>{escape(author)}</b> · Принял в работу: ___________</td>
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
		<td>Развёртка = сумма полок + завальцовки (без поправки на гиб). Углы — между полками. Пунктир — сторона покрытия. Знак «рукопожатие» на эскизе — планки стыкуются замком.</td>
		<td style="text-align:right">Factory Platform · ПМК Парк</td>
	</tr></table>
	</body></html>"""


