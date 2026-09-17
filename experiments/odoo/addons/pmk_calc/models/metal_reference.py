# -*- coding: utf-8 -*-
"""Справочник сортамента: табличные массы ГОСТ.

Массы НЕ вычисляются формулой сечения на лету — это значения из официальных
таблиц. Причина: расчётная масса по номинальным размерам расходится с
табличной (у профилей есть уклоны полок, радиусы закруглений, допуски), и
для отгрузочных документов нужна именно табличная.
"""

from odoo import api, fields, models


class MetalProfileType(models.Model):
    """Вид проката. Нужен, чтобы в расчёте сначала выбирался вид, а типоразмер
    искался уже внутри него: в общем списке из 665 позиций не найтись."""

    _name = "pmk.metal.profile.type"
    _description = "Вид проката"
    _order = "sequence, name"

    name = fields.Char("Вид проката", required=True)
    gost = fields.Char("Основной стандарт")
    sequence = fields.Integer("Порядок", default=10)


class MetalProfile(models.Model):
    """Линейный прокат: уголок, швеллер, двутавр, труба, арматура, полоса.

    Трубы ВГП лежат здесь же, а не отдельной моделью: математика у них та же —
    килограммы на погонный метр. Отдельными они были в ERPNext только из-за
    своей структуры полей (условный проход, наружный диаметр, стенка), и это
    заставляло выбирать «вид проката» из трёх вариантов вместо двух.
    Структурные поля сохранены, они просто пустуют у остального проката.
    """

    _name = "pmk.metal.profile"
    _description = "Сортамент: линейный прокат"
    _order = "profile_type, size_label"
    _rec_name = "display_name"

    type_id = fields.Many2one("pmk.metal.profile.type", "Вид проката", required=True, index=True)
    profile_type = fields.Char("Вид проката (текст)", required=True, index=True)
    gost = fields.Char("Стандарт", required=True)
    size_label = fields.Char("Типоразмер", required=True)
    mass_per_meter = fields.Float(
        "Масса, кг/м", required=True, digits=(12, 4),
        help="Табличное значение ГОСТ. Масса погонного метра.",
    )
    # Только у труб ВГП: наружный диаметр фиксирован для каждого условного
    # прохода — на него режется трубная резьба.
    du = fields.Integer("Ду, мм")
    outer_mm = fields.Float("Наружный, мм", digits=(6, 2))
    wall_mm = fields.Float("Стенка, мм", digits=(6, 2))

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

