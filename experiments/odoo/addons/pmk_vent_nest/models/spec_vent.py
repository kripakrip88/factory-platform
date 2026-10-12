# -*- coding: utf-8 -*-
"""Вентзонты во вкладке «Металл» расчёта (12.10.2026): выбранный инженером вариант
раскроя (склад / бухта, свес) по каждому цвету — строки «что купить»."""
from html import escape

from markupsafe import Markup

from odoo import fields, models

from odoo.addons.pmk_calc.models.spec_metal import rows_table
from .nest_material import fmt_mm


class MetalSpecVent(models.Model):
    _inherit = "pmk.metal.spec"

    metal_vent_html = fields.Html("Вентзонты (металл)", compute="_compute_metal_vent_html", sanitize=False)

    def _pmk_metal_rows_vent(self):
        rows = []
        for order in self.vent_order_ids:
            for m in order.nest_material_ids:
                r = m._row(int(m.sves), m.choice)
                where = "склад 2500" if m.choice == "stock" else "с бухты 1250"
                amount = "%s: %s" % (where, r.get("lengths") or r.get("error") or "—")
                if int(m.sves) < 150:
                    amount += "; свес %s" % m.sves
                rows.append({"kind": "Лист", "material": "%s · %s мм" % (m.color, fmt_mm(m.thickness)),
                             "source": order.name, "amount": amount, "kg": r.get("kg") or 0.0})
        return rows

    def _pmk_buy_rows(self):
        rows = super()._pmk_buy_rows()
        if self.cat_vent:
            rows += self._pmk_metal_rows_vent()
        return rows

    def _compute_metal_vent_html(self):
        for spec in self:
            spec.metal_vent_html = Markup(rows_table(
                spec._pmk_metal_rows_vent(),
                empty="Раскрой вентзонтов ещё не считали — «Рассчитать раскрой» во вкладке «Раскрой» "
                      "заказа вентзонтов."))
