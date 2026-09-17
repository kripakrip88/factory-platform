# -*- coding: utf-8 -*-
"""Справочник сортамента: табличные массы ГОСТ.

Массы НЕ вычисляются формулой сечения на лету — это значения из официальных
таблиц. Причина: расчётная масса по номинальным размерам расходится с
табличной (у профилей есть уклоны полок, радиусы закруглений, допуски), и
для отгрузочных документов нужна именно табличная.
"""

from odoo import api, fields, models


class MetalProfile(models.Model):
    """Линейный прокат: уголок, швеллер, двутавр, труба, арматура, полоса."""

    _name = "pmk.metal.profile"
    _description = "Сортамент: линейный прокат"
    _order = "profile_type, size_label"
    _rec_name = "display_name"

    profile_type = fields.Char("Вид проката", required=True, index=True)
    gost = fields.Char("Стандарт", required=True)
    size_label = fields.Char("Типоразмер", required=True)
    mass_per_meter = fields.Float(
        "Масса, кг/м", required=True, digits=(12, 4),
        help="Табличное значение ГОСТ. Масса погонного метра.",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("profile_type", "size_label")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.profile_type} {rec.size_label}".strip()


class MetalSheet(models.Model):
    """Лист: гладкий, рифлёный, просечно-вытяжной."""

    _name = "pmk.metal.sheet"
    _description = "Сортамент: лист"
    _order = "sheet_type, thickness_mm"
    _rec_name = "display_name"

    sheet_type = fields.Char("Вид листа", required=True, index=True)
    thickness_mm = fields.Float("Толщина, мм", required=True, digits=(6, 2))
    size_label = fields.Char("Размер")
    gost = fields.Char("Стандарт", required=True)
    mass_per_sqm = fields.Float(
        "Масса, кг/м²", required=True, digits=(12, 4),
        help="У гладкого листа это толщина × 7.85 (ГОСТ 19903-2015), "
             "у рифлёного и ПВЛ — табличное значение с учётом рифлей и просечки.",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("sheet_type", "thickness_mm", "size_label")
    def _compute_display_name(self):
        for rec in self:
            size = f" {rec.size_label}" if rec.size_label else ""
            # Толщину показываем без хвоста нулей: «4 мм», а не «4.00 мм».
            thick = ("%g" % rec.thickness_mm)
            rec.display_name = f"Лист {rec.sheet_type.lower()} {thick} мм{size}"


class MetalGrade(models.Model):
    """Марки стали. В арифметике не участвуют — нужны для документов."""

    _name = "pmk.metal.grade"
    _description = "Марка стали"
    _order = "is_default desc, name"

    name = fields.Char("Марка", required=True)
    standard = fields.Char("Стандарт", required=True)
    is_default = fields.Boolean("По умолчанию")


class MetalVgp(models.Model):
    """Трубы водогазопроводные, ГОСТ 3262-75.

    Вынесены отдельно, потому что у них наружный диаметр фиксирован для каждого
    условного прохода (на него режется трубная резьба), а с толщиной стенки
    меняется внутренний проход — в общий справочник профилей это не ложится.
    """

    _name = "pmk.metal.vgp"
    _description = "Сортамент: труба ВГП"
    _order = "du, wall_mm"
    _rec_name = "display_name"

    du = fields.Integer("Ду, мм", required=True)
    outer_mm = fields.Float("Наружный, мм", required=True, digits=(6, 2))
    wall_mm = fields.Float("Стенка, мм", required=True, digits=(6, 2))
    mass_per_meter = fields.Float("Масса, кг/м", required=True, digits=(12, 4))
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("du", "wall_mm")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "Труба ВГП Ду%s×%g" % (rec.du, rec.wall_mm)
