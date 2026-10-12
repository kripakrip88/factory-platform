# -*- coding: utf-8 -*-
"""Прокат металлоизделий во вкладке «Металл» расчёта (12.10.2026).

«Раскрой сортамента считается из расчёта сам»: кнопка «Разложить прокат» заводит (или
берёт последний) раскрой этого расчёта, переносит линейные детали («Заполнить из
расчёта») и считает. Результат — таблица во вкладке и строки «что купить»; сам раскрой
(схемы, заготовки со склада, печать) открывается кнопкой — прежний документ РК-….
"""
from html import escape

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.pmk_calc.models.spec_metal import rows_table


class MetalSpecLinear(models.Model):
    _inherit = "pmk.metal.spec"

    cut_plan_ids = fields.One2many("pmk.cut.plan", "spec_id", "Раскрой сортамента")
    metal_linear_html = fields.Html("Прокат (металл)", compute="_compute_metal_linear_html", sanitize=False)

    def _pmk_cut_plan(self):
        self.ensure_one()
        return self.cut_plan_ids.sorted("id")[-1:]

    def action_pmk_cut_linear(self):
        self.ensure_one()
        plan = self._pmk_cut_plan() or self.env["pmk.cut.plan"].create({
            "spec_id": self.id, "partner_id": self.partner_id.id or False})
        plan.action_fill_from_spec()
        plan.action_compute()
        return True

    def action_pmk_open_cut(self):
        self.ensure_one()
        plan = self._pmk_cut_plan()
        if not plan:
            raise UserError(_("Прокат ещё не раскладывали — нажмите «Разложить прокат»."))
        return {"type": "ir.actions.act_window", "res_model": "pmk.cut.plan", "res_id": plan.id,
                "views": [(False, "form")], "target": "current"}

    def _pmk_metal_rows_linear(self):
        plan = self._pmk_cut_plan()
        rows = []
        for r in plan.result_ids:
            amount = "%d заг., %s м" % (r.bars_used, ("%.1f" % (r.stock_mm / 1000.0)).replace(".", ","))
            if r.unplaced_text:
                amount += "; не размещено: %s" % r.unplaced_text
            rows.append({"kind": "Прокат", "material": r.profile_id.display_name, "source": plan.name,
                         "amount": amount, "kg": r.weight_total})
        return rows

    def _pmk_buy_rows(self):
        rows = super()._pmk_buy_rows()
        if self.cat_metal:
            rows += self._pmk_metal_rows_linear()
        return rows

    def _compute_metal_linear_html(self):
        for spec in self:
            plan = spec._pmk_cut_plan()
            if not plan:
                spec.metal_linear_html = Markup('<p class="pmk-metal-muted">%s</p>' % escape(
                    "Прокат ещё не раскладывали. «Разложить прокат» — раскрой по хлыстам из прайса."))
                continue
            rows = spec._pmk_metal_rows_linear()
            note = ""
            if plan.result_ids:
                note = '<p class="pmk-metal-muted">%s · отход %s · в лом %s кг</p>' % (
                    escape(plan.name), escape(plan.waste_label or ""),
                    ("%.1f" % (plan.scrap_weight or 0)).replace(".", ","))
            spec.metal_linear_html = Markup(note + rows_table(
                rows, with_source=False,
                empty="Раскрой %s ещё не посчитан — «Разложить прокат»." % plan.name))
