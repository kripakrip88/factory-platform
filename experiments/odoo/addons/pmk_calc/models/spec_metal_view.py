# -*- coding: utf-8 -*-
"""Вкладка «Металл» одной таблицей с раскрытием и схемой (15.10.2026).

Антон 15.10: «почему листы по раскладке и детали — две разные таблицы? Лист
раскрывается как спецификация, и в нём видно, что именно входит. То же — прокат.
Иметь возможность открыть посмотреть, как входят детали» (прототип принят,
правка: на схеме проката одинаковые отрезки — одним блоком «100 мм × 100 шт»).

Данные для виджета pmk_metal_overview (static/src/js/metal_overview.js):
  pmk_metal_overview()        — строки листа (группы раскладки + детали) и
                                прокат (pmk_cut дописывает «bars»);
  pmk_metal_sheet_scheme(id)  — листы группы с координатами деталей.
Числа — те же, что раскладка уже записала (листов, использование); схема —
та же раскладка (sheeting.group_drawings), ничего не пересчитывает в базе.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .sheeting import DEFAULT_KERF_MM, group_drawings, part_label
from .spec_layout import SHEET_SIZES
from .spec_metal import SIZE_RE

SIZE_LABELS = dict(SHEET_SIZES)


def _sheet_area_m2(size):
    m = SIZE_RE.match(size or "")
    return int(m.group(1)) * int(m.group(2)) / 1e6 if m else 0.0


class SheetGroupOverview(models.Model):
    _inherit = "pmk.metal.spec.sheet.group"

    def _pmk_sheets_buy(self):
        """Сколько листов группы покупать. Технический расчёт (pmk_tech) —
        «Листов по факту» инженера, если вписан."""
        self.ensure_one()
        return self.sheets

    def _pmk_sheet_kg(self):
        self.ensure_one()
        return _sheet_area_m2(self.sheet_size) * (self.sheet_id.mass_per_sqm or 0.0)

    def _pmk_overview_row(self):
        self.ensure_one()
        material = self.sheet_id.display_name or _("Лист не выбран")
        if self.grade_id:
            material += ", " + self.grade_id.display_name
        buy = self._pmk_sheets_buy()
        lines = self.line_ids.sorted(lambda l: (l.product_id.sequence, l.product_id.id, l.sequence, l.id))
        return {
            "id": self.id,
            "material": material,
            "size": SIZE_LABELS.get(self.sheet_size, self.sheet_size or ""),
            "sheets": self.sheets,
            "sheets_buy": buy,
            "use_label": self.use_label or "",
            "use_level": self.use_level or "",
            "mode_label": self.mode_label or "",
            "buy_kg": buy * self._pmk_sheet_kg(),
            "parts": [line._pmk_overview_part() for line in lines],
        }


class SpecLineOverview(models.Model):
    _inherit = "pmk.metal.spec.line"

    def _pmk_overview_part(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.detail_name or _("Деталь"),
            "product": self.product_id.name or "",
            "size": self.detail_size_label or "",
            "qty": (self.qty or 0) * (self.product_id.qty or 0),
            "sheet_size": self.layout_sheet_size or "",
            "sheets": self.layout_sheets or 0,
            "net_kg": (self.weight_total or 0.0) * (self.product_id.qty or 0),
        }


class MetalSpecOverview(models.Model):
    _inherit = "pmk.metal.spec"

    def pmk_metal_overview(self):
        self.ensure_one()
        self.check_access("read")
        groups = self.layout_group_ids.sorted("sequence")
        loose = self.sheet_line_ids.filtered(lambda l: not l.layout_group_id)
        return {
            "kind": getattr(self, "pmk_kind", "kp") or "kp",
            "can_write": self.has_access("write"),
            "sheet_sizes": SHEET_SIZES,
            "sheet_lines": len(self.sheet_line_ids),
            "stale": bool(self.layout_stale),
            "stale_text": self.layout_stale_text or "",
            "sheets": [group._pmk_overview_row() for group in groups],
            "loose": [line._pmk_overview_part() for line in loose],
            "bars": None,
        }

    def pmk_metal_sheet_scheme(self, group_id):
        """Листы группы с координатами деталей (x, w — поперёк листа)."""
        self.ensure_one()
        self.check_access("read")
        group = self.layout_group_ids.filtered(lambda g: g.id == group_id)
        if not group:
            raise UserError(_("Раскладка изменилась — нажмите «Разложить листы»."))
        lines = group.line_ids.sorted(lambda l: (l.product_id.sequence, l.product_id.id, l.sequence, l.id))
        if not lines:
            return {"drawings": []}
        width, length = lines[0]._layout_sheet_dims()
        parts = [(line.id, line.a_mm or 0.0, line.b_mm or 0.0,
                  (line.qty or 0) * (line.product_id.qty or 0)) for line in lines]
        result = group_drawings(width, length, parts, kerf_mm=DEFAULT_KERF_MM,
                                joint=bool(group.sheet_id))
        labels = {line.id: {"name": line.detail_name or _("Деталь"),
                            "size": part_label(line.a_mm, line.b_mm),
                            "product": line.product_id.name or ""} for line in lines}
        return {
            "width": width,
            "length": length,
            "title": "%s · %s" % (group._pmk_overview_row()["material"],
                                  SIZE_LABELS.get(group.sheet_size, group.sheet_size or "")),
            "sheets": result["sheets"],
            "more": result["more"],
            "parts": labels,
            "drawings": [{"count": d["count"],
                          "rects": [[key, round(x, 1), round(y, 1), round(w, 1), round(l, 1)]
                                    for key, x, y, w, l in d["rects"]]}
                         for d in result["drawings"]],
        }

    def pmk_metal_set_sheet_size(self, line_id, size):
        """Габарит листа детали из раскрытой строки вкладки «Металл»."""
        self.ensure_one()
        self.check_access("write")
        if size not in SIZE_LABELS:
            raise UserError(_("Нет такого габарита листа."))
        line = self.sheet_line_ids.filtered(lambda l: l.id == line_id)
        if line and line.layout_sheet_size != size:
            line.layout_sheet_size = size
            # Смена габарита гасит черновую раскладку — раскладываем сразу
            # (Антон 15.10: «0 листов — как получилось?»). «Листов по факту»
            # технолога раскладка не трогает (pmk_tech).
            self.action_draft_layout()
        return True
