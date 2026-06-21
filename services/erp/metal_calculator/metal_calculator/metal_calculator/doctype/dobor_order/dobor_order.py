# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

import json

from frappe.model.document import Document
from frappe.utils import flt, cint


class DoborOrder(Document):
	"""Заказ доборных элементов — позиции (снимки профилей) + авто-итоги.

	Источник истины для чисел — metal_calculator.dobor.api.compute (тот же, что
	серверный calc и конструктор). При сохранении каждая позиция пересчитывается
	из profile_snapshot_json, чтобы цифры в заказе/PDF/конструкторе совпадали.
	"""

	def validate(self):
		from metal_calculator.dobor.api import compute, mass_per_sqm

		total_qty = 0
		total_area = 0.0
		total_weight = 0.0
		for it in (self.items or []):
			snap = {}
			if it.profile_snapshot_json:
				try:
					snap = json.loads(it.profile_snapshot_json)
				except Exception:
					snap = {}
			flanges = snap.get("segs") or snap.get("flanges") or []
			hem_len = flt(snap.get("hemLen") or 0)
			thickness = flt(it.thickness)
			plank = flt(it.plank_length) or 2500
			qty = cint(it.qty) or 0
			if flanges and thickness > 0:
				res = compute(flanges, bool(snap.get("hemLeft")), bool(snap.get("hemRight")),
				              hem_len, mass_per_sqm(thickness), plank, qty or 1)
				it.developed_width = res["developed_width"]
				it.area_total = round(res["area_one"] * qty, 4)
				it.weight_total = round(res["weight_one"] * qty, 3)
			total_qty += qty
			total_area += flt(it.area_total)
			total_weight += flt(it.weight_total)

		self.total_positions = len(self.items or [])
		self.total_qty = total_qty
		self.total_area = round(total_area, 3)
		self.total_weight = round(total_weight, 3)
