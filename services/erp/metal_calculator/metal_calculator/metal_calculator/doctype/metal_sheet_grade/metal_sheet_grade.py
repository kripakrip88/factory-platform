# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class MetalSheetGrade(Document):
	"""Лист: масса 1 м² из ГОСТ. Гладкий (т×7.85), рифлёный, просечно-вытяжной."""

	def autoname(self):
		# format:{thickness} НЕ работает: Frappe-формат не подставляет Float-поля.
		# Контроллерный autoname надёжен. Имя зависит от типа листа:
		#   Гладкий            → «Лист-4мм»
		#   Рифлёный           → «Лист рифл-4мм ромб»
		#   Просечно-вытяжной  → «ПВЛ-406»  (№ карты из size_label)
		t = "%gмм" % flt(self.thickness)
		label = (self.size_label or "").strip()
		if self.sheet_type == "Рифлёный":
			self.name = ("Лист рифл-%s %s" % (t, label)).strip()
		elif self.sheet_type == "Просечно-вытяжной":
			self.name = "ПВЛ-%s" % (label or t)
		else:
			self.name = "Лист-%s" % t

	def validate(self):
		if self.thickness is None or self.thickness <= 0:
			frappe.throw("Толщина листа должна быть больше нуля")
		if self.mass_per_sqm is None or self.mass_per_sqm <= 0:
			frappe.throw("Масса 1 м² должна быть больше нуля")
