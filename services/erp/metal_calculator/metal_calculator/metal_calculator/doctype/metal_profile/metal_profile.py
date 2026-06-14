# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MetalProfile(Document):
	"""Профиль сортамента (линейный прокат). Масса 1 м — строго из ГОСТ, не вычисляется."""

	def validate(self):
		if self.mass_per_meter is None or self.mass_per_meter <= 0:
			frappe.throw("Масса 1 м должна быть больше нуля")
