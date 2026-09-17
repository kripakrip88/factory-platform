# -*- coding: utf-8 -*-
"""Доборные элементы: развёртка, вес, расход металла.

Перенос с ERPNext. Ядро расчёта (_compute_dobor) — точный порт функции
compute из dobor/api.py, которая и в исходнике была чистой, без фреймворка.
Формулы не трогались намеренно: по ним печатают производственные листы,
и расхождение здесь означало бы брак в цеху.

Что считаем:
  развёртка = сумма полок + завальцовки × длина завальцовки
  площадь    = развёртка × длина планки (обе в метрах)
  вес        = площадь × масса 1 м² по толщине
  гибов      = (полок − 1) + завальцовки + 2, если замок
  полос из рулона = ширина рулона // развёртка, остаток — отход
"""

import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError

MM_IN_M = 1000.0
STEEL_DENSITY_FACTOR = 7.85  # кг на м² при толщине 1 мм


class DoborCoating(models.Model):
    _name = "pmk.dobor.coating"
    _description = "Покрытие доборки"
    _order = "name"

    name = fields.Char("Покрытие", required=True)
    ral_code = fields.Char("RAL")
    hex_color = fields.Char("Цвет", help="Образец цвета для подбора на экране")


class DoborProfile(models.Model):
    """Шаблон профиля: сохранённая форма сечения для повторного использования."""

    _name = "pmk.dobor.profile"
    _description = "Шаблон профиля доборки"
    _order = "name"

    name = fields.Char("Название профиля", required=True)
    flanges_json = fields.Text(
        "Полки (JSON)", required=True, default="[]",
        help='Список полок: [{"len": 100, "dir": 0}, ...]. Длины в мм, dir — направление гиба.')
    hem_left = fields.Boolean("Завальцовка слева")
    hem_right = fields.Boolean("Завальцовка справа")
    hem_len = fields.Float("Длина завальцовки, мм", default=10.0)
    lock = fields.Boolean("Замок", help="Специальное соединение, добавляет два гиба")
    paint_side = fields.Integer("Сторона окраски", default=1)


class DoborOrder(models.Model):
    _name = "pmk.dobor.order"
    _description = "Заказ доборных элементов"
    _inherit = ["mail.thread"]
    _order = "order_date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    customer = fields.Char("Клиент / изделие", tracking=True)
    order_date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    state = fields.Selection(
        [("draft", "Черновик"), ("confirmed", "В работе"), ("done", "Изготовлен")],
        "Статус", default="draft", tracking=True)
    line_ids = fields.One2many("pmk.dobor.order.line", "order_id", "Доборки", copy=True)

    total_positions = fields.Integer("Позиций", compute="_compute_totals", store=True)
    total_qty = fields.Integer("Планок, шт", compute="_compute_totals", store=True)
    total_area = fields.Float("Площадь, м²", compute="_compute_totals", store=True, digits=(12, 4))
    total_weight = fields.Float("Вес, кг", compute="_compute_totals", store=True, digits=(12, 3))

    @api.depends("line_ids.weight_total", "line_ids.area_total", "line_ids.qty")
    def _compute_totals(self):
        for order in self:
            order.total_positions = len(order.line_ids)
            order.total_qty = sum(order.line_ids.mapped("qty"))
            order.total_area = sum(order.line_ids.mapped("area_total"))
            order.total_weight = sum(order.line_ids.mapped("weight_total"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.dobor.order") or "Черновик"
        return super().create(vals_list)


class DoborOrderLine(models.Model):
    _name = "pmk.dobor.order.line"
    _description = "Позиция заказа доборки"
    _order = "sequence, id"

    order_id = fields.Many2one("pmk.dobor.order", "Заказ", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    title = fields.Char("Название доборки", required=True)
    coating_id = fields.Many2one("pmk.dobor.coating", "Покрытие")
    thickness = fields.Float("Толщина, мм", required=True, default=0.5, digits=(6, 2))
    plank_length = fields.Float("Длина планки, мм", required=True, default=2000.0, digits=(12, 1))
    qty = fields.Integer("Количество, шт", required=True, default=1)
    coil_width = fields.Float("Ширина рулона, мм", digits=(12, 1),
                              help="Если задана — считается, сколько полос выходит из рулона и какой остаётся отход")

    # Форма сечения. Хранится снимком, а не ссылкой на шаблон: шаблон могут
    # потом поправить, а заказ должен остаться таким, каким его изготовили.
    profile_snapshot_json = fields.Text("Снимок профиля (JSON)", default="[]")
    hem_left = fields.Boolean("Завальцовка слева")
    hem_right = fields.Boolean("Завальцовка справа")
    hem_len = fields.Float("Длина завальцовки, мм", default=10.0, digits=(6, 2))
    lock = fields.Boolean("Замок")

    developed_width = fields.Float("Развёртка, мм", compute="_compute_dobor", store=True, digits=(12, 2))
    bends = fields.Integer("Гибов", compute="_compute_dobor", store=True)
    area_one = fields.Float("Площадь шт, м²", compute="_compute_dobor", store=True, digits=(12, 4))
    area_total = fields.Float("Площадь всего, м²", compute="_compute_dobor", store=True, digits=(12, 4))
    weight_one = fields.Float("Вес шт, кг", compute="_compute_dobor", store=True, digits=(12, 3))
    weight_total = fields.Float("Вес всего, кг", compute="_compute_dobor", store=True, digits=(12, 3))
    strips = fields.Integer("Полос из рулона", compute="_compute_dobor", store=True)
    strip_waste = fields.Float("Отход рулона, мм", compute="_compute_dobor", store=True, digits=(12, 2))

    def _mass_per_sqm(self, thickness):
        """Масса 1 м² по толщине: сперва справочник, иначе толщина × 7.85.

        Порядок важен и сохранён из исходника: у гладкого листа табличное
        значение ГОСТ и есть толщина × 7.85, но для нестандартных толщин
        (0.4, 0.45, 0.7 — обычные для доборки) записи в справочнике нет,
        и формула остаётся единственным источником.
        """
        sheet = self.env["pmk.metal.sheet"].search(
            [("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", thickness)], limit=1)
        return sheet.mass_per_sqm if sheet else thickness * STEEL_DENSITY_FACTOR

    @api.depends("profile_snapshot_json", "hem_left", "hem_right", "hem_len",
                 "lock", "thickness", "plank_length", "qty", "coil_width")
    def _compute_dobor(self):
        for line in self:
            try:
                snapshot = json.loads(line.profile_snapshot_json or "[]")
            except (ValueError, TypeError):
                snapshot = []
            flanges = snapshot.get("segs", []) if isinstance(snapshot, dict) else snapshot

            flange_sum = sum(float(f.get("len") or 0) for f in flanges if isinstance(f, dict))
            hem_count = (1 if line.hem_left else 0) + (1 if line.hem_right else 0)
            developed = flange_sum + hem_count * line.hem_len

            area_one = (developed / MM_IN_M) * (line.plank_length / MM_IN_M)
            weight_one = area_one * line._mass_per_sqm(line.thickness)

            # Завальцовка — это подгиб 180°, то есть тоже гиб; замок добавляет два.
            line.bends = max(0, len(flanges) - 1) + hem_count + (2 if line.lock else 0)
            line.developed_width = developed
            line.area_one = area_one
            line.area_total = area_one * (line.qty or 0)
            line.weight_one = weight_one
            line.weight_total = weight_one * (line.qty or 0)

            if developed > 0 and line.coil_width > 0:
                line.strips = int(line.coil_width // developed)
                line.strip_waste = line.coil_width - line.strips * developed
            else:
                line.strips = 0
                line.strip_waste = line.coil_width or 0.0

    @api.constrains("thickness", "plank_length", "qty")
    def _check_positive(self):
        for line in self:
            if line.thickness <= 0:
                raise ValidationError("Толщина должна быть больше нуля.")
            if line.plank_length <= 0:
                raise ValidationError("Длина планки должна быть больше нуля.")
            if line.qty <= 0:
                raise ValidationError("Количество должно быть больше нуля.")
