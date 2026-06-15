# Copyright (c) 2026, Factory Platform and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CuttingPlan(Document):
	"""План раскроя металла (линейный 1D или листовой 2D). Расчёт — в cutting.api."""

	def validate(self):
		if not self.plan_title:
			self.plan_title = f"Раскрой ({self.cut_type or 'Линейный'})"
