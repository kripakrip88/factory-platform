# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class StockLength(Document):
	"""Справочник стандартных длин хлыста (6000, 11700, 12000…)."""

	def autoname(self):
		# format:{length_mm} не подставляет Float → контроллерный autoname.
		self.name = "%g мм" % flt(self.length_mm)

	def validate(self):
		if self.length_mm is None or self.length_mm <= 0:
			frappe.throw("Длина хлыста должна быть больше нуля")
