# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import flt


class MetalSpec(Document):
	"""Спецификация металла — накопленные позиции расчёта с итогом по весу."""

	def validate(self):
		self.total_positions = len(self.items or [])
		self.total_weight_kg = sum(flt(i.weight_total_kg) for i in (self.items or []))
