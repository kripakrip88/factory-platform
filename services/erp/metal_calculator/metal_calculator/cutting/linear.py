# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""
Линейный раскрой (1D) — First Fit Decreasing. ЧИСТЫЕ функции, без frappe.

Каждая деталь занимает piece_length + kerf (консервативно). Деловой остаток не
выделяем: всё, что не деталь — отход. Через детали протягивается наименование
(detail_name) — для сводки «что куда режется».
"""

EPS = 1e-9


def ffd_1d(stock_length, kerf, pieces):
	"""First Fit Decreasing. pieces — список (length, label).

	Возвращает список хлыстов, каждый — список (length, label) деталей в нём.
	"""
	bins = []
	for length, label in sorted(pieces, key=lambda p: -p[0]):
		need = length + kerf
		for b in bins:
			if b["used"] + need <= stock_length + EPS:
				b["used"] += need
				b["pieces"].append((length, label))
				break
		else:
			bins.append({"used": need, "pieces": [(length, label)]})
	return [b["pieces"] for b in bins]


def _pattern_key(pieces):
	"""Ключ паттерна — мультимножество (длина, наименование) для группировки одинаковых хлыстов."""
	return tuple(sorted(pieces, key=lambda p: (-p[0], p[1])))


def plan_linear(stock_length, kerf, items):
	"""Полный план линейного раскроя.

	items — список dict: {profile_type, size_label, piece_length, qty, detail_name?}.
	Группируем по (profile_type, size_label). Деталь длиннее хлыста → ошибка группы,
	не падаем. Возвращает {"groups":[...], "total_stock":int, "waste_percent":float}.
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
		pieces = []
		for r in rows:
			pl = float(r.get("piece_length") or 0)
			qty = int(r.get("qty") or 0)
			label = (r.get("detail_name") or "").strip()
			pieces.extend([(pl, label)] * qty)

		oversize = sorted({pl for pl, _ in pieces if pl + kerf > stock_length + EPS}, reverse=True)
		if oversize:
			groups_out.append({
				"profile_type": profile_type, "size_label": size_label,
				"error": f"Деталь длиннее хлыста ({stock_length:g} мм): {', '.join('%g' % x for x in oversize)}",
				"stock_count": 0, "patterns": [], "waste_percent": 0.0,
			})
			continue

		bins = ffd_1d(stock_length, kerf, pieces)
		stock_count = len(bins)

		pat = {}
		pat_order = []
		for bp in bins:
			k = _pattern_key(bp)
			if k not in pat:
				pat[k] = {"pieces": list(bp), "count": 0}
				pat_order.append(k)
			pat[k]["count"] += 1
		patterns = []
		for k in pat_order:
			bp = pat[k]["pieces"]
			used = sum(p[0] for p in bp)
			patterns.append({
				"pieces": [{"length": p[0], "label": p[1]} for p in bp],
				"count": pat[k]["count"], "used": used, "waste": stock_length - used,
			})

		group_used = sum(sum(p[0] for p in bp) for bp in bins)
		group_cap = stock_count * stock_length
		waste_pct = ((group_cap - group_used) / group_cap * 100) if group_cap else 0.0

		groups_out.append({
			"profile_type": profile_type, "size_label": size_label, "error": None,
			"stock_count": stock_count, "patterns": patterns, "waste_percent": round(waste_pct, 2),
		})
		total_stock += stock_count
		total_used_len += group_used

	total_cap = total_stock * stock_length
	total_waste_pct = ((total_cap - total_used_len) / total_cap * 100) if total_cap else 0.0
	return {"groups": groups_out, "total_stock": total_stock, "waste_percent": round(total_waste_pct, 2)}
