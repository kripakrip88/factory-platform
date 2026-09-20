# -*- coding: utf-8 -*-
"""Печатный лист раскроя для цеха.

Вёрстка собирается здесь строкой, а не в QWeb — тем же приёмом, что и лист
доборки. Причины две. Первая: стандартный макет Odoo тащит свою шапку и свои
стили, а лист чёрно-белый и выверен под печать. Вторая: полоски схем должны
быть таблицей с процентными ширинами, потому что PDF рисует старый движок,
и на flexbox полагаться нельзя — на бумаге он поедет.
"""

import json

from markupsafe import Markup, escape

from odoo import models


class PmkCutPlanSheet(models.Model):
    _inherit = "pmk.cut.plan"

    def _sheet_html(self):
        self.ensure_one()
        parts = [_CSS, self._sheet_header()]
        for result in self.result_ids:
            parts.append(self._sheet_result(result))
        parts.append(self._sheet_footer())
        # Обёртка class="article" ОБЯЗАТЕЛЬНА, и вот почему. Odoo ищет в
        # свёрстанной странице блоки с этим классом и каждый оборачивает в
        # свой minimal_layout, где есть <meta charset="utf-8">. Если ни
        # одного такого блока нет, срабатывает запасной путь: в файл для
        # wkhtmltopdf уходит голый фрагмент БЕЗ объявления кодировки, и
        # кириллица печатается как «Ð›Ð¸ÑÑ Ñ€Ð°ÑÐºÑ€Ð¾Ñ».
        return Markup(
            '<div class="article" data-oe-model="%s" data-oe-id="%s">'
            '<div class="cut">%s</div></div>'
            % (self._name, self.id, "".join(parts)))

    # ------------------------------------------------------------------

    def _sheet_header(self):
        rows = [("Дата", self.date and self.date.strftime("%d.%m.%Y") or "—")]
        if self.partner_id:
            rows.append(("Клиент", self.partner_id.display_name))
        if self.note:
            rows.append(("Примечание", self.note))
        rows.append(("Ширина пропила", "%s мм" % self._fmt(self.kerf_mm)))
        rows.append(("Годный остаток от", "%s мм" % self._fmt(self.min_useful_mm)))

        cells = "".join(
            '<tr><td class="k">%s</td><td class="v">%s</td></tr>' % (escape(k), escape(v))
            for k, v in rows
        )
        return (
            '<div class="head">'
            '<div class="title">Лист раскроя %s</div>'
            '<table class="meta">%s</table>'
            '</div>' % (escape(self.name), cells)
        )

    def _sheet_result(self, result):
        patterns = result.get_patterns()
        blocks = [
            '<div class="grp">'
            '<div class="grp-name">%s</div>'
            '<div class="grp-sum">заготовок: <b>%s</b> · взято %s кг · '
            'в детали %s кг · в остатки %s кг · в лом %s кг</div>'
            % (escape(result.profile_id.display_name), result.bars_used,
               self._fmt(result.weight_total), self._fmt(result.weight_parts),
               self._fmt(result.leftover_weight), self._fmt(result.scrap_weight))
        ]

        for pattern in patterns:
            blocks.append(self._sheet_pattern(pattern))

        if result.leftovers_text:
            blocks.append(
                '<div class="rest">Годные остатки на склад: <b>%s</b></div>'
                % escape(result.leftovers_text))
        if result.unplaced_text:
            blocks.append(
                '<div class="bad">НЕ РАЗМЕЩЕНО: %s</div>' % escape(result.unplaced_text))

        blocks.append('</div>')
        return "".join(blocks)

    def _sheet_pattern(self, pattern):
        """Одна схема: полоска с отрезками в масштабе и подписями.

        Ширины в процентах и таблицей — так полоска остаётся в масштабе на
        бумаге. Подпись дублируется цифрой под ячейкой: на узкой ячейке
        текст внутри не помещается, а размер знать надо.
        """
        total = pattern["stock_length"] or 1
        cells, labels = [], []
        for piece in pattern["pieces"]:
            width = 100.0 * piece / total
            cells.append('<td class="p" style="width:%.3f%%">%s</td>'
                         % (width, escape(self._fmt(piece))))
            labels.append('<td class="l" style="width:%.3f%%">%s</td>'
                          % (width, escape(self._fmt(piece))))
        leftover = pattern["leftover"]
        if leftover > 0:
            width = 100.0 * leftover / total
            css = "u" if leftover >= self.min_useful_mm else "s"
            cells.append('<td class="r %s" style="width:%.3f%%">%s</td>'
                         % (css, width, escape(self._fmt(leftover))))
            labels.append('<td class="l" style="width:%.3f%%">%s</td>'
                          % (width, escape(self._fmt(leftover))))

        return (
            '<div class="pat">'
            '<div class="pat-head">%s мм &#215; %s</div>'
            '<table class="bar"><tr>%s</tr></table>'
            '<table class="bar lab"><tr>%s</tr></table>'
            '</div>' % (escape(self._fmt(pattern["stock_length"])), pattern["count"],
                        "".join(cells), "".join(labels))
        )

    def _sheet_footer(self):
        return (
            '<div class="total">Итого по документу: заготовок <b>%s</b>, '
            'взято <b>%s кг</b>, в лом <b>%s кг</b> (%s%%)</div>'
            '<div class="sign">Разметил ______________ &nbsp;&nbsp; '
            'Нарезал ______________ &nbsp;&nbsp; Дата ____________</div>'
            % (self.total_bars, self._fmt(self.total_weight),
               self._fmt(self.scrap_weight), self._fmt(self.waste_ratio))
        )


class PmkCutResultSheet(models.Model):
    _inherit = "pmk.cut.result"

    def get_patterns(self):
        """Схемы из сохранённого расчёта — печати и виду нужны одни и те же."""
        self.ensure_one()
        if not self.result_json:
            return []
        try:
            return json.loads(self.result_json).get("patterns") or []
        except (ValueError, TypeError):
            return []


# Лист чёрно-белый: цветной принтер в цеху редкость, а серые заливки
# печатаются одинаково на любом. Поля страницы задаются здесь, в самом листе,
# поэтому в формате бумаги они нулевые — иначе сложатся и макет поедет.
_CSS = """<style>
@page { size: A4 portrait; margin: 12mm; }
.cut { font-family: Arial, sans-serif; font-size: 10pt; color: #000; }
.cut .title { font-size: 16pt; font-weight: bold; margin-bottom: 6px; }
.cut .meta { border-collapse: collapse; margin-bottom: 10px; }
.cut .meta .k { padding: 1px 12px 1px 0; color: #444; }
.cut .meta .v { padding: 1px 0; font-weight: bold; }
.cut .grp { margin-top: 14px; padding-top: 8px; border-top: 1.5px solid #000;
            page-break-inside: avoid; }
.cut .grp-name { font-size: 12pt; font-weight: bold; }
.cut .grp-sum { font-size: 9pt; color: #333; margin: 2px 0 8px; }
.cut .pat { margin-bottom: 10px; page-break-inside: avoid; }
.cut .pat-head { font-size: 9.5pt; margin-bottom: 2px; }
.cut .bar { width: 100%; border-collapse: collapse; table-layout: fixed; }
.cut .bar td { height: 22px; text-align: center; font-size: 8.5pt;
               border: 1px solid #000; overflow: hidden; }
.cut .bar .p { background: #e8e8e8; }
.cut .bar .r.u { background: #ffffff; }
/* Лом штриховкой: на чёрно-белой печати заливка и рамка уже заняты, а
   отличать его от годного остатка надо с одного взгляда. */
.cut .bar .r.s { background: #b8b8b8; }
.cut .bar.lab td { height: auto; border: 0; font-size: 7.5pt; color: #333;
                   padding-top: 1px; }
.cut .rest { font-size: 9.5pt; margin-top: 4px; }
.cut .bad { font-size: 10pt; font-weight: bold; margin-top: 6px;
            padding: 4px 6px; border: 2px solid #000; }
.cut .total { margin-top: 16px; padding-top: 8px; border-top: 2px solid #000;
              font-size: 11pt; }
.cut .sign { margin-top: 26px; font-size: 9.5pt; }
</style>"""
