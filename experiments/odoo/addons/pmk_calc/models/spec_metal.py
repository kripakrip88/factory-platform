# -*- coding: utf-8 -*-
"""Вкладка «Металл» расчёта (12.10.2026): лист, прокат, доборки, зонты и «что купить».

Каждая категория даёт строки металла (_pmk_buy_rows): вид (лист / прокат), материал,
откуда (металлоизделия, доборка ДОБ-…, вентзонты ВЗ-…), что купить словами и килограммы.
Здесь — лист металлоизделий (раскладка расчёта) и раскрой листа доборок; прокат добавляет
pmk_cut (раскрой сортамента), вентзонты — pmk_vent_nest (раскрой «склад / бухта»).
Итог «что купить» — одна таблица по всем строкам. Считается на чтении, ничего не хранит.
"""
import re
from html import escape

from markupsafe import Markup

from odoo import fields, models

from odoo.addons.pmk_calc.tools import dobor_cut as C
from .spec_layout import SHEET_SIZES

SIZE_RE = re.compile(r"^(\d+)x(\d+)$")


def kg_text(v):
    s = ("{:,.1f}".format(v)).replace(",", " ").replace(".", ",")
    return s[:-2] if s.endswith(",0") else s


def rows_table(rows, with_source=True, empty=""):
    """Строки металла → HTML-таблица (общая для разделов вкладки и итога)."""
    if not rows:
        return '<p class="pmk-metal-muted">%s</p>' % escape(empty) if empty else ""
    head = "<tr><th>Вид</th><th>Материал</th>%s<th>Что купить</th><th class=\"n\">Металл, кг</th></tr>" % (
        "<th>Откуда</th>" if with_source else "")
    body = "".join(
        "<tr><td>%s</td><td>%s</td>%s<td>%s</td><td class=\"n\">%s</td></tr>" % (
            escape(r["kind"]), escape(r["material"]),
            "<td>%s</td>" % escape(r["source"]) if with_source else "",
            escape(r["amount"]), kg_text(r["kg"]) if r.get("kg") else "—")
        for r in rows)
    total = sum(r.get("kg") or 0 for r in rows)
    foot = '<tr class="pmk-metal-total"><td colspan="%d">Итого</td><td class="n">%s</td></tr>' % (
        4 if with_source else 3, kg_text(total))
    return '<table class="pmk-metal-table"><thead>%s</thead><tbody>%s</tbody><tfoot>%s</tfoot></table>' % (
        head, body, foot)


class MetalSpecMetal(models.Model):
    _inherit = "pmk.metal.spec"

    metal_sheet_note = fields.Html("Лист металлоизделий (итог)", compute="_compute_metal_html", sanitize=False)
    metal_dobor_html = fields.Html("Доборки (металл)", compute="_compute_metal_html", sanitize=False)
    metal_total_html = fields.Html("Что купить", compute="_compute_metal_html", sanitize=False)

    # ------------------------------------------------------------ строки
    def _pmk_metal_rows_sheet(self):
        """Лист металлоизделий — группы раскладки (сколько листов какого габарита)."""
        rows = []
        sizes = dict(SHEET_SIZES)
        for g in self.layout_group_ids.filtered(lambda g: g.sheets):
            m = SIZE_RE.match(g.sheet_size or "")
            area = int(m.group(1)) * int(m.group(2)) / 1e6 if m else 0.0
            mass = g.sheet_id.mass_per_sqm or 0.0
            material = g.sheet_id.display_name or "лист"
            if g.grade_id:
                material += ", " + g.grade_id.display_name
            rows.append({"kind": "Лист", "material": material, "source": "Металлоизделия",
                         "amount": "%d × %s" % (g.sheets, sizes.get(g.sheet_size, g.sheet_size or "")),
                         "kg": g.sheets * area * mass})
        # Детали без группы (листы не раскладывали черновиком или расчёт старый) — по
        # оценке «каждая деталь отдельно»: листы складываются по листу и габариту.
        loose = {}
        for line in self.sheet_line_ids.filtered(lambda l: l.layout_sheets and not l.layout_group_id):
            key = (line.sheet_id, line.layout_sheet_size)
            loose[key] = loose.get(key, 0) + line.layout_sheets
        for (sheet, size), count in loose.items():
            m = SIZE_RE.match(size or "")
            area = int(m.group(1)) * int(m.group(2)) / 1e6 if m else 0.0
            rows.append({"kind": "Лист", "material": sheet.display_name or "лист", "source": "Металлоизделия",
                         "amount": "%d × %s (по деталям, без раскладки)" % (count, sizes.get(size, size or "")),
                         "kg": count * area * (sheet.mass_per_sqm or 0.0)})
        return rows

    def _pmk_metal_rows_dobor(self):
        """Доборки — раскрой листа выбранного в доборке варианта (стандарт / с бухты)."""
        rows = []
        for order in self.dobor_order_ids:
            src = order.cut_source
            for g in order._cut_groups().values():
                try:
                    v = C.plan(g["strips"], g["mass"])[src]
                except C.CutError as e:
                    rows.append({"kind": "Лист", "material": g["title"], "source": order.name,
                                 "amount": "не раскроить: %s" % e, "kg": 0.0})
                    continue
                if src == "stock":
                    amount = "%d × 1250 × 2500" % v["sheets"]
                else:
                    parts = []
                    if v["sheets"]:
                        parts.append("с бухты 1250: %s" % v["sheet_lengths"])
                    if v.get("ready"):
                        parts.append("готовые заготовки 1250 × (%s)" % v["ready_lengths"])
                    amount = "; ".join(parts)
                rows.append({"kind": "Лист", "material": g["title"], "source": order.name,
                             "amount": amount, "kg": v["kg"]})
        return rows

    def _pmk_buy_rows(self):
        """Все строки «что купить». Модули категорий дописывают свои (super() + строки)."""
        self.ensure_one()
        rows = []
        if self.cat_metal:
            rows += self._pmk_metal_rows_sheet()
        if self.cat_dobor:
            rows += self._pmk_metal_rows_dobor()
        return rows

    def _compute_metal_html(self):
        for spec in self:
            sheet = spec._pmk_metal_rows_sheet() if spec.cat_metal else []
            dobor = spec._pmk_metal_rows_dobor() if spec.cat_dobor else []
            spec.metal_sheet_note = Markup(rows_table(sheet, with_source=False)) if sheet else False
            spec.metal_dobor_html = Markup(rows_table(
                dobor, empty="В доборке нет позиций с развёрткой — раскраивать нечего."))
            spec.metal_total_html = Markup(rows_table(
                spec._pmk_buy_rows(),
                empty="Пока нечего покупать: разложите лист, прокат, доборки и зонты."))
