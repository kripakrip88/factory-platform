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

from .cut_plan import PRICE_BAR_PRIORITY
from .cutting import bar_name


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
                parts.append("%d заг., %s м" % (r.bars_used, _m(r.stock_mm)))
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


# Длины хлыста на выбор во вкладке «Металл» (Антон 15.10.2026: «длину хлыста
# нельзя менять? может быть 6, 12, 9 метров, арматура 11,7»).
BAR_LENGTHS = [6000, 9000, 11700, 12000]


class MetalSpecLinearOverview(models.Model):
    """Прокат во вкладке «Металл» одной таблицей со схемой (15.10.2026,
    pmk_calc/models/spec_metal_view.py): строка — типоразмер раскроя,
    раскрывается в отрезки по изделиям; «Схема» — хлысты блоками
    «200 мм × 8» (Антон: сто полосок по 100 мм на 12 м нечитабельны)."""
    _inherit = "pmk.metal.spec"

    def _pmk_linear_parts(self):
        """{профиль: (чистый вес, [отрезки])} по линейным строкам расчёта."""
        parts = {}
        products = self.product_ids.sorted(lambda p: (p.sequence, p.id))
        for product in products:
            for line in product.line_linear_ids.sorted(lambda l: (l.sequence, l.id)):
                # Прокат «по КМ» (масса, №307) не режется — он в «Итого — что купить».
                if not line.profile_id or line.pmk_mass_kg:
                    continue
                net, rows = parts.setdefault(line.profile_id.id, (0.0, []))
                qty = (line.qty or 0) * (product.qty or 0)
                rows.append({"id": line.id, "name": line.detail_name or "Отрезок",
                             "product": product.name or "", "length": line.length_mm or 0.0,
                             "qty": qty})
                parts[line.profile_id.id] = (net + (line.weight_total or 0.0) * (product.qty or 0), rows)
        return parts

    def pmk_metal_overview(self):
        data = super().pmk_metal_overview()
        plan = self.cut_plan_ids.filtered("result_ids").sorted("id")[-1:]
        parts = self._pmk_linear_parts()
        bars = []
        for result in plan.result_ids:
            net, rows = parts.get(result.profile_id.id, (0.0, []))
            unplaced = max(0.0, net - (result.weight_parts or 0.0))
            stocks = plan.stock_ids.filtered(lambda st, pr=result.profile_id: st.profile_id == pr)
            bars.append({
                "id": result.id,
                "profile_id": result.profile_id.id,
                "lengths": sorted({round(st.length_mm) for st in stocks if not st.qty}),
                "own_stock": len(stocks.filtered("qty")),
                "material": result.profile_id.display_name,
                "bars": result.bars_used,
                "stock_m": (result.stock_mm or 0.0) / 1000.0,
                "parts_m": (result.parts_mm or 0.0) / 1000.0,
                "buy_kg": (result.weight_total or 0.0) + unplaced,
                "leftovers": result.leftovers_text or "",
                "unplaced": result.unplaced_text or "",
                "parts": rows,
            })
        loose = [dict(row, material=self.env["pmk.metal.profile"].browse(pid).display_name)
                 for pid, (_net, rows) in parts.items()
                 if pid not in plan.result_ids.profile_id.ids for row in rows]
        data["bars"] = {
            "bar_lengths": BAR_LENGTHS,
            "plan": plan.name or "",
            "plan_id": plan.id or False,
            "has_linear": bool(parts),
            "rows": bars,
            "loose": loose,
        }
        return data

    def pmk_metal_bar_scheme(self, result_id):
        """Схемы раскроя типоразмера: одинаковые отрезки подряд — одним блоком."""
        self.ensure_one()
        self.check_access("read")
        result = self.cut_plan_ids.result_ids.filtered(lambda r: r.id == result_id)
        if not result:
            raise UserError(_("Раскрой изменился — нажмите «Разложить прокат»."))
        res = json.loads(result.result_json or "{}")
        min_useful = result.plan_id.min_useful_mm or 0.0
        patterns = []
        for pattern in res.get("patterns", []):
            blocks = []
            for piece in pattern.get("pieces", []):
                if blocks and abs(blocks[-1]["length"] - piece) < 0.05:
                    blocks[-1]["qty"] += 1
                else:
                    blocks.append({"length": piece, "qty": 1})
            leftover = pattern.get("leftover") or 0.0
            patterns.append({
                "count": pattern.get("count") or 1,
                "stock": pattern.get("stock_length") or 0.0,
                "blocks": blocks,
                "leftover": leftover,
                "useful": leftover >= min_useful,
            })
        return {
            "title": "%s · %s" % (result.profile_id.display_name, result.plan_id.name),
            "plan_id": result.plan_id.id,
            "patterns": patterns,
            "unplaced": result.unplaced_text or "",
        }

    def pmk_metal_set_bar_lengths(self, profile_id, lengths):
        """Какими хлыстами докупать типоразмер: отмеченные длины — заготовки
        «сколько нужно» последнего раскроя (вместо прежних докупаемых, в том
        числе «из прайса»); свои заготовки и обрезки (с количеством) — как
        были. Раскрой пересчитывается сразу."""
        self.ensure_one()
        self.check_access("write")
        lengths = sorted({int(length) for length in lengths or [] if int(length) in BAR_LENGTHS})
        if not lengths:
            raise UserError(_("Отметьте хотя бы одну длину хлыста."))
        plan = self.cut_plan_ids.filtered("result_ids").sorted("id")[-1:] or self._pmk_cut_plan()
        if not plan:
            raise UserError(_("Прокат ещё не раскладывали — нажмите «Разложить прокат»."))
        profile = self.env["pmk.metal.profile"].browse(profile_id).exists()
        if not profile:
            raise UserError(_("Типоразмер не найден."))
        plan.stock_ids.filtered(lambda st: st.profile_id == profile and not st.qty).unlink()
        self.env["pmk.cut.stock"].create([{
            "plan_id": plan.id, "profile_id": profile.id, "length_mm": float(length), "qty": 0,
            "priority": PRICE_BAR_PRIORITY, "name": "%s (докупка)" % bar_name(length),
        } for length in lengths])
        plan.action_compute()
        return True
