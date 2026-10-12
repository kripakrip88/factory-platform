# -*- coding: utf-8 -*-
"""Раскрой листа доборки: вкладка «Раскрой листа» заказа доборки (12.10.2026).

Доборки рубят на гильотине со стандартного листа 1250 × 2500 или с бухты (лист нужной
длины, кратно 50) — решения Антона и алгоритм в tools/dobor_cut.py. Здесь — сбор
заготовок заказа по материалу (металл + покрытие), выбор варианта и экран: сравнение
«стандарт / бухта» по каждому материалу и карты раскроя выбранного варианта.
Считается на лету (жадная раскладка — миллисекунды), ничего не хранится, кроме выбора.
"""
from html import escape

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.pmk_calc.tools import dobor_cut as C


def _kg(v):
    s = ("%.1f" % v).replace(".", ",")
    return s[:-2] if s.endswith(",0") else s


class DoborOrderLineCut(models.Model):
    _inherit = "pmk.dobor.order.line"

    @api.constrains("plank_length")
    def _check_plank_length_cut(self):
        for line in self:
            if line.plank_length > C.MAX_LEN:
                raise ValidationError(
                    "Длина планки — до %d мм: гильотина и гибка не берут длиннее (%s: %d мм)."
                    % (C.MAX_LEN, line.display_name, line.plank_length))


class DoborOrderCut(models.Model):
    _inherit = "pmk.dobor.order"

    cut_source = fields.Selection(
        [("stock", "Стандартный лист 1250 × 2500"), ("coil", "С бухты (длина кратна 50, до 2500)")],
        "Лист", required=True, default="stock",
        help="Обычно — стандартный лист. С бухты лист рубят нужной длины: меньше отхода по длине. "
             "Карты раскроя ниже — для выбранного варианта.")
    cut_html = fields.Html("Раскрой листа", compute="_compute_cut_html", sanitize=False)

    def _cut_groups(self):
        """{(металл, покрытие): {"title", "mass", "strips"}} — заготовки заказа по материалу."""
        self.ensure_one()
        groups = {}
        lines = self.line_ids.sorted(lambda l: (l.sequence, l.id))
        for n, line in enumerate(lines, 1):
            if not (line.developed_width and line.plank_length and line.qty):
                continue
            key = (line.sheet_id.id, line.coating_id.id)
            if key not in groups:
                metal = line.sheet_id.display_name or ("лист %g мм" % (line.thickness or 0))
                groups[key] = {
                    "title": " · ".join(filter(None, [line.coating_id.name, metal])),
                    "mass": line.sheet_id.mass_per_sqm or line._mass_per_sqm(line.thickness),
                    "strips": [],
                }
            groups[key]["strips"].append((line.developed_width, line.plank_length, "№%d" % n, line.qty))
        return groups

    @api.depends("cut_source", "line_ids.developed_width", "line_ids.plank_length", "line_ids.qty",
                 "line_ids.sheet_id", "line_ids.coating_id", "line_ids.sequence")
    def _compute_cut_html(self):
        for order in self:
            order.cut_html = order._cut_render()

    def _cut_render(self):
        self.ensure_one()
        groups = self._cut_groups()
        if not groups:
            return Markup('<p class="pmk-cut-muted">Нет позиций с развёрткой — раскраивать нечего.</p>')
        out = []
        for g in groups.values():
            head = '<div class="pmk-cut-mat"><h4 class="pmk-cut-title">%s</h4>' % escape(g["title"])
            try:
                res = C.plan(g["strips"], g["mass"])
            except C.CutError as e:
                out.append(head + '<p class="text-danger">%s</p></div>' % escape(str(e)))
                continue
            rows = []
            for src, name in (("stock", "Стандарт 1250 × 2500"), ("coil", "С бухты")):
                v = res[src]
                cls = ' class="pmk-cut-chosen"' if src == self.cut_source else ""
                rows.append('<tr%s><th>%s</th><td>%d</td><td>%s</td><td>%s</td><td>%s %%</td></tr>' % (
                    cls, name, v["sheets"], escape(v["lengths"]), _kg(v["kg"]),
                    _kg(v["util_pct"])))
            table = ('<table class="pmk-cut-table"><thead><tr><th>Лист</th><th>Листов</th><th>Длины, мм</th>'
                     '<th>Металл, кг</th><th>Использование</th></tr></thead><tbody>%s</tbody></table>'
                     % "".join(rows))
            sv = res["saving"]
            note = ("С бухты экономия %s кг (%s %%) против стандарта." % (_kg(sv["kg"]), _kg(sv["pct"]))
                    if sv["kg"] > 0.05 else "С бухты экономии нет — стандартный лист.")
            chosen = res[self.cut_source]
            maps = "".join('<div class="pmk-cut-map">%s</div>' % C.sheet_svg(m) for m in chosen["maps"])
            out.append(head + table + '<p class="pmk-cut-note">%s</p>' % note
                       + '<div class="pmk-cut-maps">%s</div></div>' % maps)
        legend = ('<p class="pmk-cut-muted">Гильотина: лист рубится поперёк на ленты (рез 1250 мм), лента — '
                  'вдоль на заготовки «развёртка × длина» (рез до 2500 мм). На заготовке — номер позиции. '
                  'Штриховка — отход.</p>')
        return Markup('<div class="pmk-cut">%s%s</div>' % ("".join(out), legend))
