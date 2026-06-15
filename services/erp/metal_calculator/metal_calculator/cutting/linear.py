# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
Линейный раскрой (1D) — First Fit Decreasing.

ЧИСТЫЕ функции, без frappe — тестируются отдельно. Все размеры в мм.
Каждая деталь занимает piece_length + kerf (консервативно: рез на каждую деталь).
Деловой остаток не выделяем: всё, что не деталь — отход.
"""

EPS = 1e-9


def ffd_1d(stock_length, kerf, lengths):
	"""First Fit Decreasing. lengths — список длин деталей (мм).

	Возвращает список хлыстов, каждый — список длин деталей в нём.
	"""
	bins = []  # каждый: {"used": занятая длина (с резами), "pieces": [len,...]}
	for length in sorted(lengths, reverse=True):
		need = length + kerf
		for b in bins:
			if b["used"] + need <= stock_length + EPS:
				b["used"] += need
				b["pieces"].append(length)
				break
		else:
			bins.append({"used": need, "pieces": [length]})
	return [b["pieces"] for b in bins]


def _pattern_key(pieces):
	"""Ключ паттерна хлыста — мультимножество длин (для группировки одинаковых)."""
	return tuple(sorted(pieces, reverse=True))


def plan_linear(stock_length, kerf, items):
	"""Полный план линейного раскроя.

	items — список dict: {profile_type, size_label, piece_length, qty}.
	Группируем по (profile_type, size_label) — каждый сортамент отдельно.
	Возвращает {"groups": [...], "total_stock": int, "waste_percent": float}.
	Деталь длиннее хлыста → группа помечается ошибкой, расчёт НЕ падает.
	"""
	grouped = {}
	order = []
	for it in items:
		key = (it.get("profile_type") or "", it.get("size_label") or "")
		if key not in grouped:
			grouped[key] = []
			order.append(key)
		grouped[key].append(it)

	groups_out = []
	total_stock = 0
	total_used_len = 0.0

	for key in order:
		profile_type, size_label = key
		rows = grouped[key]
		# развернуть детали по qty
		lengths = []
		for r in rows:
			pl = float(r.get("piece_length") or 0)
			qty = int(r.get("qty") or 0)
			lengths.extend([pl] * qty)

		# проверка: деталь длиннее хлыста (с учётом реза)
		oversize = sorted({pl for pl in lengths if pl + kerf > stock_length + EPS}, reverse=True)
		if oversize:
			groups_out.append({
				"profile_type": profile_type, "size_label": size_label,
				"error": f"Деталь длиннее хлыста ({stock_length:g} мм): {', '.join('%g' % x for x in oversize)}",
				"stock_count": 0, "patterns": [], "waste_percent": 0.0,
			})
			continue

		bins = ffd_1d(stock_length, kerf, lengths)
		stock_count = len(bins)

		# сгруппировать одинаковые паттерны
		pat = {}
		pat_order = []
		for pieces in bins:
			k = _pattern_key(pieces)
			if k not in pat:
				pat[k] = {"pieces": list(k), "count": 0}
				pat_order.append(k)
			pat[k]["count"] += 1
		patterns = []
		for k in pat_order:
			pieces = pat[k]["pieces"]
			used = sum(pieces)
			waste = stock_length - used  # отход хлыста этого паттерна (включая резы)
			patterns.append({"pieces": pieces, "count": pat[k]["count"],
			                 "used": used, "waste": waste})

		group_used = sum(sum(b) for b in bins)
		group_capacity = stock_count * stock_length
		waste_pct = ((group_capacity - group_used) / group_capacity * 100) if group_capacity else 0.0

		groups_out.append({
			"profile_type": profile_type, "size_label": size_label, "error": None,
			"stock_count": stock_count, "patterns": patterns,
			"waste_percent": round(waste_pct, 2),
		})
		total_stock += stock_count
		total_used_len += group_used

	total_cap = total_stock * stock_length
	total_waste_pct = ((total_cap - total_used_len) / total_cap * 100) if total_cap else 0.0
	return {"groups": groups_out, "total_stock": total_stock,
	        "waste_percent": round(total_waste_pct, 2)}
