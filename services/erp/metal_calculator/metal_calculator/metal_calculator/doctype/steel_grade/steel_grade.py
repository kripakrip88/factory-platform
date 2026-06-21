# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SteelGrade(Document):
	"""Марка стали. На расчёт веса НЕ влияет — атрибут изделия."""

	def validate(self):
		# Марка по умолчанию должна быть единственной.
		if self.is_default:
			frappe.db.set_value(
				"Steel Grade",
				{"is_default": 1, "name": ("!=", self.name)},
				"is_default",
				0,
				update_modified=False,
			)
