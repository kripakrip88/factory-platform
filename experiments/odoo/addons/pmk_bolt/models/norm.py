# -*- coding: utf-8 -*-
"""Нормы для фундаментных болтов по диаметру: металл и работа.

Антон 21.10.2026: «цены условные, но их нужно перепроверять» — таблицу правит
Владимир; у строки видно, когда и кто последний раз проверял цифры. Изменил
цену — дата проверки ставится сама.

Круг по маркам — здесь, а не из прайсов: на 21.10 круг есть в прайсах у 5 из
54 размеров и без марки (Ст3 и 09Г2С по одной цене). Цена прайса — подсказкой.
"""
from odoo import api, fields, models

PRICE_FIELDS = ("round_st3_ton", "round_09g2s_ton", "sheet_ton", "thread_rub", "bend_rub", "turn_rub",
                "plate_rub", "washer_rub")
STALE_DAYS = 90


class BoltNorm(models.Model):
    _name = "pmk.bolt.norm"
    _description = "Нормы для фундаментных болтов"
    _order = "diameter"
    _rec_name = "diameter"

    diameter = fields.Integer("М", required=True)
    round_st3_ton = fields.Float("Круг Ст3, ₽/т", digits=(12, 0))
    round_09g2s_ton = fields.Float("Круг 09Г2С, ₽/т", digits=(12, 0))
    sheet_ton = fields.Float("Лист (плита, шайба), ₽/т", digits=(12, 0))
    thread_rub = fields.Float("Резьба, ₽", digits=(12, 0),
                              help="Нарезка одного конца на длину по ГОСТ. Длиннее — пропорционально.")
    bend_rub = fields.Float("Гиб, ₽", digits=(12, 0), help="Один гиб.")
    turn_rub = fields.Float("Проточка, ₽", digits=(12, 0), help="Один конец (тип 2.2).")
    plate_rub = fields.Float("Плита, работа ₽", digits=(12, 0), help="Резка плиты и отверстие.")
    washer_rub = fields.Float("Шайба, работа ₽", digits=(12, 0))
    checked_on = fields.Date("Проверено", readonly=True)
    checked_by = fields.Many2one("res.users", "Кем", readonly=True)
    stale = fields.Boolean("Пора проверить", compute="_compute_stale",
                           help="Не проверяли ни разу или больше %s дней." % STALE_DAYS)
    note = fields.Char("Заметка")

    _diameter_uniq = models.Constraint("UNIQUE(diameter)", "Норма на диаметр — одна.")

    @api.depends("checked_on")
    def _compute_stale(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.stale = not rec.checked_on or (today - rec.checked_on).days > STALE_DAYS

    def write(self, vals):
        if set(PRICE_FIELDS) & set(vals) and "checked_on" not in vals:
            vals = dict(vals, checked_on=fields.Date.context_today(self), checked_by=self.env.uid)
        return super().write(vals)

    def action_mark_checked(self):
        self.write({"checked_on": fields.Date.context_today(self), "checked_by": self.env.uid})

    @api.model
    def _pmk_for(self, diameter):
        return self.search([("diameter", "=", diameter)], limit=1)
