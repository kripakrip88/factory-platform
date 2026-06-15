# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
Листовой гильотинный раскрой (2D) — полочный (shelf) с поворотом 90°. ЧИСТЫЕ функции.

Только прямоугольники, гильотинные резы, БЕЗ вкладывания. Оси: sheet_length по X,
sheet_width по Y. kerf — между деталями и полками. Через детали протягивается
наименование (detail_name) — для подписи на эскизе и сводки.
"""

EPS = 1e-9


def fits_sheet(L, W, sheet_l, sheet_w):
	"""Влезает ли деталь хотя бы в одной из двух ориентаций (0°/90°)."""
	return (L <= sheet_l + EPS and W <= sheet_w + EPS) or (W <= sheet_l + EPS and L <= sheet_w + EPS)


def shelf_2d(sheet_l, sheet_w, kerf, parts):
	"""Полочная укладка с поворотом 90°. parts — список (L, W, label).

	Каждая деталь должна влезать на лист (проверка до вызова). Возвращает список
	листов; каждый — список размещений {x, y, w, h, rot, label, L, W}.
	"""
	items = sorted(parts, key=lambda p: -max(p[0], p[1]))
	sheets = []

	def open_sheet():
		s = {"placements": [], "shelf_y": 0.0, "shelf_h": 0.0, "used_x": 0.0}
		sheets.append(s)
		return s

	s = open_sheet()
	for (L, W, label) in items:
		placed = False
		for _attempt in range(3):
			x_start = s["used_x"] + (kerf if s["used_x"] > 0 else 0)
			options = []
			for (pl, ph, rot) in ((L, W, 0), (W, L, 1)):
				if pl > sheet_l + EPS or ph > sheet_w + EPS:
					continue
				if x_start + pl <= sheet_l + EPS:
					new_h = max(s["shelf_h"], ph)
					if s["shelf_y"] + new_h <= sheet_w + EPS:
						options.append((new_h - s["shelf_h"], ph, pl, rot))
			if options:
				options.sort()
				_, ph, pl, rot = options[0]
				s["placements"].append({"x": x_start, "y": s["shelf_y"], "w": pl, "h": ph,
				                        "rot": rot, "label": label, "L": L, "W": W})
				s["used_x"] = x_start + pl
				s["shelf_h"] = max(s["shelf_h"], ph)
				placed = True
				break
			if s["used_x"] > 0:
				ny = s["shelf_y"] + s["shelf_h"] + kerf
				feasible = any(
					pl <= sheet_l + EPS and ph <= sheet_w + EPS and ny + ph <= sheet_w + EPS
					for (pl, ph) in ((L, W), (W, L))
				)
				if feasible:
					s["shelf_y"], s["shelf_h"], s["used_x"] = ny, 0.0, 0.0
					continue
			s = open_sheet()
		if not placed:
			raise ValueError(f"Деталь {L}x{W} не удалось разместить")
	return sheets


def plan_sheet(sheet_l, sheet_w, kerf, items):
	"""Полный план листового раскроя. items — {size_label, piece_length, piece_width, qty, detail_name?}.

	Группируем по size_label (толщина). Деталь не влезает ни в одной ориентации →
	ошибка группы (не падать). Одинаковые листы группируются (count). Возвращает
	{"groups":[...], "total_stock":int, "waste_percent":float}.
	"""
	grouped = {}
	order = []
	for it in items:
		key = it.get("size_label") or ""
		if key not in grouped:
			grouped[key] = []
			order.append(key)
		grouped[key].append(it)

	sheet_area = sheet_l * sheet_w
	groups_out = []
	total_stock = 0
	total_part_area = 0.0

	for key in order:
		rows = grouped[key]
		parts = []
		for r in rows:
			L = float(r.get("piece_length") or 0)
			W = float(r.get("piece_width") or 0)
			qty = int(r.get("qty") or 0)
			label = (r.get("detail_name") or "").strip()
			parts.extend([(L, W, label)] * qty)

		bad = sorted({(L, W) for (L, W, _) in parts if not fits_sheet(L, W, sheet_l, sheet_w)})
		if bad:
			groups_out.append({
				"size_label": key,
				"error": f"Деталь не влезает на лист {sheet_l:g}×{sheet_w:g} мм (ни в одной ориентации): "
				         + ", ".join("%g×%g" % (L, W) for (L, W) in bad),
				"sheet_count": 0, "sheets": [], "waste_percent": 0.0,
			})
			continue

		sheets = shelf_2d(sheet_l, sheet_w, kerf, parts)
		sheet_count = len(sheets)
		part_area = sum(L * W for (L, W, _) in parts)
		cap = sheet_count * sheet_area
		waste_pct = ((cap - part_area) / cap * 100) if cap else 0.0

		# Сгруппировать одинаковые листы (раскладка + наименования) → один эскиз + count.
		sig_map = {}
		sig_order = []
		for sh in sheets:
			sig = tuple(sorted(
				(round(p["x"], 2), round(p["y"], 2), round(p["w"], 2), round(p["h"], 2), p["rot"], p["label"])
				for p in sh["placements"]
			))
			if sig not in sig_map:
				sig_map[sig] = {"placements": sh["placements"], "count": 0, "summary": _sheet_summary(sh["placements"])}
				sig_order.append(sig)
			sig_map[sig]["count"] += 1
		unique_sheets = [sig_map[sig] for sig in sig_order]

		groups_out.append({
			"size_label": key, "error": None, "sheet_count": sheet_count,
			"sheets": unique_sheets, "waste_percent": round(waste_pct, 2),
		})
		total_stock += sheet_count
		total_part_area += part_area

	total_cap = total_stock * sheet_area
	total_waste_pct = ((total_cap - total_part_area) / total_cap * 100) if total_cap else 0.0
	return {"groups": groups_out, "total_stock": total_stock, "waste_percent": round(total_waste_pct, 2)}


def _sheet_summary(placements):
	"""Сводка по листу: [{label, L, W, count}] — что и сколько на этом листе."""
	agg = {}
	order = []
	for p in placements:
		k = (p["label"], p["L"], p["W"])
		if k not in agg:
			agg[k] = 0
			order.append(k)
		agg[k] += 1
	return [{"label": k[0], "L": k[1], "W": k[2], "count": agg[k]} for k in order]
