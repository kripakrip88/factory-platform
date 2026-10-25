# -*- coding: utf-8 -*-
"""Поправка на гиб круга (Антон 25.10.2026): «каждый гиб убирает 2 диаметра с развёртки, как с
фундаментными болтами… вынести в настройки калькулятора, тогда для каждого диаметра технолог
сможет вносить свои коэффициенты».

Заготовка гнутой детали из круга = сумма наружных размеров − гибов × коэффициент × ⌀.
Нет строки для диаметра — коэффициент 2. Сейчас по ней считается скоба МН1 (⌀18, 4 гиба).
"""
from odoo import api, fields, models

DEFAULT_K = 2.0


class KolodecBend(models.Model):
    _name = "pmk.kolodec.bend"
    _description = "Поправка на гиб круга"
    _order = "diameter"
    _rec_name = "diameter"

    diameter = fields.Integer("Диаметр круга, мм", required=True)
    factor = fields.Float("Вычет на 1 гиб, диаметров", required=True, default=DEFAULT_K, digits=(6, 2),
                          help="Сколько диаметров убирает с развёртки один гиб 90°. По умолчанию 2.")
    deduction_mm = fields.Float("Вычет на 1 гиб, мм", compute="_compute_deduction", digits=(8, 1))
    note = fields.Char("Примечание", help="Станок, радиус, кто проверил пробным гибом.")

    _diameter_uniq = models.Constraint("UNIQUE(diameter)", "Для диаметра — одна строка.")

    @api.depends("diameter", "factor")
    def _compute_deduction(self):
        for rec in self:
            rec.deduction_mm = rec.diameter * rec.factor

    @api.model
    def _pmk_factor(self, diameter):
        rec = self.search([("diameter", "=", int(diameter))], limit=1)
        return rec.factor if rec else DEFAULT_K
