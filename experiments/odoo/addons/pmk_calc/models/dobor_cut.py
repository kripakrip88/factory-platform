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


PRINT_CSS = """
@page { size: A4; margin: 12mm; }
* { box-sizing: border-box; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 10pt; color: #000; margin: 0; }
h1 { font-size: 15pt; margin: 0 0 2mm; }
.meta { margin-bottom: 4mm; }
.meta td { padding: 0.6mm 4mm 0.6mm 0; vertical-align: top; }
.meta td.k { color: #000; font-weight: bold; }
h2 { font-size: 12pt; margin: 5mm 0 1.5mm; border-bottom: 0.4mm solid #000; padding-bottom: 1mm; }
.sum { margin: 0 0 2mm; }
table.pos { border-collapse: collapse; width: 100%; margin-bottom: 3mm; }
table.pos th, table.pos td { border: 0.25mm solid #000; padding: 0.8mm 1.5mm; text-align: left; }
table.pos td.n { text-align: right; white-space: nowrap; }
.card { page-break-inside: avoid; margin: 3mm 0 4mm; }
.card-head { font-weight: bold; margin-bottom: 1mm; }
.card-head .box { display: inline-block; width: 3.5mm; height: 3.5mm; border: 0.3mm solid #000;
                  margin-left: 3mm; vertical-align: -0.6mm; }
.steps { margin: 1mm 0 0; padding-left: 5mm; }
.steps li { margin: 0.3mm 0; }
.legend { margin-top: 4mm; font-size: 8.5pt; }
svg { display: block; width: 100%; height: auto; }
"""


class DoborOrderCutPrint(models.Model):
    _inherit = "pmk.dobor.order"

    def action_print_cut(self):
        return self.env.ref("pmk_calc.action_report_dobor_cut").report_action(self)

    def _cut_print_html(self):
        """Чёрно-белый лист раскроя для гильотины: шапка, по материалу — итог, позиции,
        карты раскроя с порядком рубки и квадратиком «сделано»."""
        self.ensure_one()
        source = self.cut_source
        src_name = dict(self._fields["cut_source"].selection)[source]
        when = fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%d.%m.%Y %H:%M")
        meta = [("Клиент", self.partner_id.display_name or "—"), ("Изделие / объект", self.customer or "—"),
                ("Дата заказа", self.order_date and self.order_date.strftime("%d.%m.%Y") or "—"),
                ("Лист", src_name), ("Напечатано", when)]
        out = ['<h1>Раскрой листа · %s</h1>' % escape(self.name),
               '<table class="meta">%s</table>' % "".join(
                   '<tr><td class="k">%s</td><td>%s</td></tr>' % (escape(k), escape(v)) for k, v in meta)]
        lines = self.line_ids.sorted(lambda l: (l.sequence, l.id))
        numbered = {line.id: n for n, line in enumerate(lines, 1)}
        for key, g in self._cut_groups().items():
            out.append("<h2>%s</h2>" % escape(g["title"]))
            try:
                res = C.plan(g["strips"], g["mass"])
            except C.CutError as e:
                out.append("<p><b>Не раскроить:</b> %s</p>" % escape(str(e)))
                continue
            v = res[source]
            out.append('<p class="sum">Листов: <b>%d</b> (%s мм) · металл %s кг · использование %s %%%s</p>' % (
                v["sheets"], escape(v["lengths"]), _kg(v["kg"]), _kg(v["util_pct"]),
                " · <b>заказать с бухты: 1250 × (%s)</b>" % escape(v["lengths"]) if source == "coil" else ""))
            rows = []
            for line in lines.filtered(lambda l, k=key: (l.sheet_id.id, l.coating_id.id) == k
                                       and l.developed_width and l.plank_length and l.qty):
                rows.append('<tr><td class="n">№%d</td><td>%s</td><td class="n">%g × %g</td><td class="n">%d</td></tr>' % (
                    numbered[line.id], escape(line.display_name), line.developed_width, line.plank_length, line.qty))
            out.append('<table class="pos"><thead><tr><th>№</th><th>Доборка</th><th>Заготовка, мм '
                       '(развёртка × длина)</th><th>Шт</th></tr></thead><tbody>%s</tbody></table>' % "".join(rows))
            for i, card in enumerate(v["maps"], 1):
                head = "Карта %d — лист 1250 × %d мм%s" % (
                    i, card["length"], (", листов: %d" % card["count"]) if card["count"] > 1 else "")
                steps = "".join("<li>%s</li>" % escape(s) for s in C.card_steps(card))
                out.append('<div class="card"><div class="card-head">%s<span class="box"></span></div>%s'
                           '<ol class="steps">%s</ol></div>' % (
                               escape(head), C.sheet_svg(card, title=" ", bw=True, width=1000.0), steps))
        out.append('<p class="legend">Гильотина: лист рубится поперёк на ленты (рез 1250 мм), лента — вдоль '
                   'на полосы «развёртка» (рез до 2500 мм). На полосе — номер позиции и размер; штриховка — '
                   'отход. Квадратик у карты — отметка «сделано».</p>')
        return Markup('<!DOCTYPE html><html><head><meta charset="utf-8"/><style>%s</style></head>'
                      '<body>%s</body></html>' % (PRINT_CSS, "".join(out)))
