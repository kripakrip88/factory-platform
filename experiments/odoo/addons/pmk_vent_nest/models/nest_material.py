# -*- coding: utf-8 -*-
"""Материал раскроя: строка «цвет + толщина» с вариантами склад/бухта и свесом.

Строки создаёт расчёт (pmk.vent.hood.order._nest_apply_plan). Инженер выбирает в строке
вариант и свес — по ним собираются программы. Подсказка («бухта выгоднее», лучший свес)
не блокирует выбор: система показывает, решает инженер.
"""
import json

from odoo import api, fields, models

SVES_VALUES = [("150", "150"), ("145", "145"), ("140", "140"), ("135", "135"),
               ("130", "130"), ("125", "125")]
SOURCES = [("stock", "Склад 2500"), ("coil", "Бухта")]


def fmt_mm(v):
    """Толщина как есть: 0,65 (не округлять до десятых, как килограммы)."""
    return ("%g" % v).replace(".", ",") if v is not None else "—"


def fmt_kg(v):
    return ("%.1f" % v).replace(".", ",").replace(",0", "") if v is not None else "—"


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
    choice_kg = fields.Float("Выбрано, кг", digits=(10, 1), compute="_compute_choice")
    choice_lengths = fields.Char("Выбрано: листы", compute="_compute_choice")

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
