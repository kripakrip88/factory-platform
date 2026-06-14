# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class MetalSheetGrade(Document):
	"""Лист: масса 1 м² по толщине — строго из ГОСТ (толщина × 7.85)."""

	def autoname(self):
		# format:Лист-{thickness}мм НЕ работает: Frappe-формат подставляет Data,
		# но не Float-поля → имя выходило «Лист-мм» (пустое) → дубликаты при сиде.
		# Контроллерный autoname надёжен: %g даёт «2.5» и «3» (без хвостового .0).
		self.name = "Лист-%gмм" % flt(self.thickness)

	def validate(self):
		if self.thickness is None or self.thickness <= 0:
			frappe.throw("Толщина листа должна быть больше нуля")
		if self.mass_per_sqm is None or self.mass_per_sqm <= 0:
			frappe.throw("Масса 1 м² должна быть больше нуля")
