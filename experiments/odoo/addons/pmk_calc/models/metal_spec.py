# -*- coding: utf-8 -*-
"""Спецификация металлопроката — расчёт веса по справочнику ГОСТ.

Перенос калькулятора с ERPNext. Арифметика та же и живёт в одном месте
(_compute_weight): вес = табличная масса × длина/площадь × количество.
Геометрии здесь нет вовсе — только выборка из справочника и умножение.

Размеры пользователь вводит в МИЛЛИМЕТРАХ, справочные массы даны в кг/м
и кг/м². Перевод мм → м делается явно в расчёте, а не прячется в данных:
именно на этом месте в подобных калькуляторах чаще всего ошибаются в тысячу раз.

Марка стали в арифметике НЕ участвует — она только атрибут для документов.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

MM_IN_M = 1000.0


class MetalSpec(models.Model):
    _name = "pmk.metal.spec"
    _description = "Спецификация металлопроката"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Клиент", tracking=True)
    note = fields.Char("Примечание")
    line_ids = fields.One2many("pmk.metal.spec.line", "spec_id", "Позиции", copy=True)

    total_weight = fields.Float(
        "Итого, кг", compute="_compute_totals", store=True, digits=(12, 3))
    total_positions = fields.Integer(
        "Позиций", compute="_compute_totals", store=True)

    @api.depends("line_ids.weight_total")
    def _compute_totals(self):
        for spec in self:
            spec.total_weight = sum(spec.line_ids.mapped("weight_total"))
            spec.total_positions = len(spec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.metal.spec") or "Черновик"
        return super().create(vals_list)


class MetalSpecLine(models.Model):
    _name = "pmk.metal.spec.line"
    _description = "Позиция спецификации"
    _order = "sequence, id"

    spec_id = fields.Many2one("pmk.metal.spec", "Спецификация", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    detail_name = fields.Char("Деталь", help="Название детали или узла — для печати")

    # Три вида проката считаются по-разному, поэтому вид выбирается явно,
    # а не угадывается по заполненным полям.
    calc_mode = fields.Selection(
        [("linear", "Линейный прокат"), ("sheet", "Лист"), ("vgp", "Труба ВГП")],
        "Вид", required=True, default="linear")

    profile_id = fields.Many2one("pmk.metal.profile", "Профиль")
    sheet_id = fields.Many2one("pmk.metal.sheet", "Лист")
    vgp_id = fields.Many2one("pmk.metal.vgp", "Труба ВГП")
    grade_id = fields.Many2one("pmk.metal.grade", "Марка стали")

    length_mm = fields.Float("Длина, мм", digits=(12, 1))
    a_mm = fields.Float("Сторона A, мм", digits=(12, 1))
    b_mm = fields.Float("Сторона B, мм", digits=(12, 1))
    qty = fields.Integer("Кол-во, шт", required=True, default=1)

    weight_one = fields.Float(
        "Вес шт, кг", compute="_compute_weight", store=True, digits=(12, 3))
    weight_total = fields.Float(
        "Вес всего, кг", compute="_compute_weight", store=True, digits=(12, 3))
    size_label = fields.Char("Типоразмер", compute="_compute_size_label", store=True)

    @api.depends("calc_mode", "profile_id", "sheet_id", "vgp_id")
    def _compute_size_label(self):
        for line in self:
            source = {
                "linear": line.profile_id,
                "sheet": line.sheet_id,
                "vgp": line.vgp_id,
            }.get(line.calc_mode)
            line.size_label = source.display_name if source else False

    @api.depends("calc_mode", "profile_id", "sheet_id", "vgp_id",
                 "length_mm", "a_mm", "b_mm", "qty")
    def _compute_weight(self):
        for line in self:
            one = 0.0
            if line.calc_mode == "linear" and line.profile_id:
                one = line.profile_id.mass_per_meter * (line.length_mm / MM_IN_M)
            elif line.calc_mode == "vgp" and line.vgp_id:
                one = line.vgp_id.mass_per_meter * (line.length_mm / MM_IN_M)
            elif line.calc_mode == "sheet" and line.sheet_id:
                # Площадь в м²: обе стороны переводим из миллиметров.
                one = line.sheet_id.mass_per_sqm * (line.a_mm / MM_IN_M) * (line.b_mm / MM_IN_M)
            line.weight_one = one
            line.weight_total = one * (line.qty or 0)

    @api.constrains("qty", "length_mm", "a_mm", "b_mm", "calc_mode")
    def _check_positive(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError("Количество должно быть больше нуля.")
            if line.calc_mode in ("linear", "vgp") and line.length_mm <= 0:
                raise ValidationError("Длина должна быть больше нуля.")
            if line.calc_mode == "sheet" and (line.a_mm <= 0 or line.b_mm <= 0):
                raise ValidationError("Стороны листа должны быть больше нуля.")

    @api.onchange("calc_mode")
    def _onchange_calc_mode(self):
        """Чистим поля другого вида, чтобы в документе не оставалось мусора."""
        if self.calc_mode == "linear":
            self.sheet_id = self.vgp_id = False
            self.a_mm = self.b_mm = 0
        elif self.calc_mode == "vgp":
            self.profile_id = self.sheet_id = False
            self.a_mm = self.b_mm = 0
        elif self.calc_mode == "sheet":
            self.profile_id = self.vgp_id = False
            self.length_mm = 0
