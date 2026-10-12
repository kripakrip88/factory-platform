# -*- coding: utf-8 -*-
"""Прокат металлоизделий во вкладке «Металл» расчёта (12.10.2026).

«Раскрой сортамента считается из расчёта сам»: кнопка «Разложить прокат» заводит (или
берёт последний) раскрой этого расчёта, переносит линейные детали («Заполнить из
расчёта») и считает. Результат — таблица во вкладке и строки «что купить»; сам раскрой
(схемы, заготовки со склада, печать) открывается кнопкой — прежний документ РК-….
"""
import json
from html import escape

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.pmk_calc.models.spec_metal import rows_table


def _m(mm):
    """Миллиметры → метры словом: 12000 → «12», 318269 → «318,3»."""
    text = ("%.1f" % (mm / 1000.0)).replace(".", ",")
    return text[:-2] if text.endswith(",0") else text


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
        """Строки проката по раскрою. Деталь длиннее самого длинного хлыста раскрой не
        разместит — в расчёте она, скорее всего, записана одной строкой «весь объём»
        (318 269 мм × 1). Тогда так и пишем и считаем металл по длине, чтобы итог
        «что купить» не занижался."""
        plan = self._pmk_cut_plan()
        rows = []
        for r in plan.result_ids:
            mass = r.profile_id.mass_per_meter or 0.0
            longest = max(plan.stock_ids.filtered(lambda s, p=r.profile_id: s.profile_id == p)
                          .mapped("length_mm") or [0])
            res = json.loads(r.result_json or "{}")
            long_mm = other = 0
            for u in res.get("unplaced", []):
                if longest and u["length"] > longest:
                    long_mm += u["length"] * u["qty"]
                else:
                    other += u["qty"]
            parts = []
            if r.bars_used:
                parts.append("%d заг., %s м" % (r.bars_used, ("%.1f" % (r.stock_mm / 1000.0)).replace(".", ",")))
            if long_mm:
                parts.append("%s м одной деталью — длиннее хлыста %s м: разбейте на детали; металл — по длине"
                             % (_m(long_mm), _m(longest)))
            if other or (r.unplaced_text and not long_mm):
                parts.append("не размещено: %s" % r.unplaced_text)
            rows.append({"kind": "Прокат", "material": r.profile_id.display_name, "source": plan.name,
                         "amount": "; ".join(parts) or "—",
                         "kg": r.weight_total + long_mm / 1000.0 * mass})
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
