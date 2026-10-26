# -*- coding: utf-8 -*-
"""Материал раскроя: строка «цвет + толщина» с вариантами склад/бухта и свесом.

Строки создаёт расчёт (pmk.vent.hood.order._nest_apply_plan). Инженер выбирает в строке
вариант и свес — по ним собираются программы. Подсказка («бухта выгоднее», лучший свес)
не блокирует выбор: система показывает, решает инженер.
"""
import json
import re

from odoo import api, fields, models

SVES_VALUES = [("150", "150"), ("145", "145"), ("140", "140"), ("135", "135"),
               ("130", "130"), ("125", "125")]
SOURCES = [("stock", "Склад 2500"), ("coil", "Бухта")]


def fmt_mm(v):
    """Толщина как есть: 0,65 (не округлять до десятых, как килограммы)."""
    return ("%g" % v).replace(".", ",") if v is not None else "—"


def fmt_kg(v):
    return ("%.1f" % v).replace(".", ",").replace(",0", "") if v is not None else "—"


def color_key(c):
    """Ключ цвета — как color_key пакета раскроя (lib/vent_nesting/api.py): «RAL8017»,
    «RAL 8017 Шоколад» → «ral8017»; пусто и «оц…» → «оц». Своя копия: импорт пакета в
    процесс Odoo тянул бы numpy и глобальное состояние раскроя."""
    s = str(c or "").strip().lower()
    m = re.search(r"ral\s*-?\s*(\d{4})", s) or re.match(r"^(\d{4})\b", s)
    if m:
        return "ral" + m.group(1)
    if not s or s.startswith(("оц", "zn", "цинк", "без покрыт")):
        return "оц"
    return re.sub(r"[\s_\-]+", "", s)


def line_key(line):
    """Ключ материала строки заказа: «ral8017|0.65» — по имени DXF генератора."""
    m = re.match(r"^vsh_\d+x\d+_t([\d.]+)_(.+)\.dxf$", line._vh_dxf_name())
    return "%s|%g" % (color_key(m.group(2)), float(m.group(1))) if m else None


class VentNestMaterial(models.Model):
    _name = "pmk.vent.nest.material"
    _description = "Раскрой вентзонтов — материал"
    _order = "sequence, id"

    order_id = fields.Many2one("pmk.vent.hood.order", "Заказ вентзонтов", required=True,
                               ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    key = fields.Char("Ключ материала", required=True, help="Как в пакете раскроя: «ral8017|0.65».")
    color = fields.Char("Цвет", required=True)
    thickness = fields.Float("Толщина, мм", digits=(6, 2))
    stock_kg = fields.Float("Склад, кг", digits=(10, 1))
    stock_lengths = fields.Char("Склад: листы")
    stock_error = fields.Char("Склад невозможен")
    coil_kg = fields.Float("Бухта, кг", digits=(10, 1))
    coil_lengths = fields.Char("Бухта: листы")
    coil_error = fields.Char("Бухта невозможна")
    recommend = fields.Selection(SOURCES, "Выгоднее")
    choice = fields.Selection(SOURCES, "Вариант", required=True, default="coil")
    sves = fields.Selection(SVES_VALUES, "Свес, мм", required=True, default="150")
    sves_json = fields.Text("Перебор свеса (JSON)",
                            help="Строки пакета: {sves, source, kg, lengths, sheets, error}.")
    price_kg = fields.Float("Цена листа, ₽/кг", compute="_compute_price",
                            help="Из прайса справочника «Лист» по толщине материала; нет цены — 0 "
                                 "(рублей экономии нет, соседнюю позицию не подставляем).")
    price_sheet = fields.Char("Лист для цены", compute="_compute_price")
    choice_kg = fields.Float("Выбрано, кг", digits=(10, 1), compute="_compute_choice")
    choice_lengths = fields.Char("Выбрано: листы", compute="_compute_choice")

    @api.depends("thickness", "order_id.line_ids.sheet_id", "order_id.line_ids.coating_id")
    def _compute_price(self):
        for rec in self:
            price, name = rec.order_id._nest_price_kg(rec.thickness, rec._lines() or None)
            rec.price_kg = price or 0.0
            rec.price_sheet = name or False

    def _lines(self):
        """Строки заказа этого материала (цвет + толщина — как ключ пакета раскроя)."""
        self.ensure_one()
        return self.order_id.line_ids.filtered(lambda l: l.spec_json and line_key(l) == self.key)

    @api.depends("choice", "sves", "sves_json", "stock_kg", "coil_kg")
    def _compute_choice(self):
        for rec in self:
            row = rec._row(rec.sves, rec.choice)
            rec.choice_kg = row.get("kg") or 0.0
            rec.choice_lengths = row.get("lengths") or row.get("error") or False

    def _rows(self):
        self.ensure_one()
        try:
            return json.loads(self.sves_json or "[]")
        except ValueError:
            return []

    def _row(self, sves, source):
        for r in self._rows():
            if int(float(r.get("sves") or 0)) == int(sves) and r.get("source") == source:
                return r
        if int(sves) == 150:
            if source == "stock":
                return {"kg": self.stock_kg, "lengths": self.stock_lengths, "error": self.stock_error}
            return {"kg": self.coil_kg, "lengths": self.coil_lengths, "error": self.coil_error}
        return {}

    def _best(self):
        """Лучшая строка перебора (меньше кг), без невозможных."""
        rows = [r for r in self._rows() if r.get("kg") and not r.get("error")]
        return min(rows, key=lambda r: (r["kg"], -float(r["sves"]))) if rows else None
