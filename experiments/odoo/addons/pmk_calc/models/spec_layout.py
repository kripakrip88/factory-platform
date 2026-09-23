# -*- coding: utf-8 -*-
"""Черновая раскладка в спецификации: сколько листов покупать под заказ.

ЗАЧЕМ КНОПКА, А НЕ АВТОМАТИЧЕСКИЙ ПЕРЕСЧЁТ. Замысел владельца: «менеджер нажал
сделать черновую раскладку и понял что надо либо идти к технологу и думать как
сэкономить либо вносит расчётную себестоимость в заказ». То есть раскладка —
это шаг решения, а не фоновая арифметика. Нажал — увидел число листов и долю
металла, и дальше выбирает сам.

Геометрия живёт отдельно, в sheeting.py: там чистые функции без базы, их
проверяют тесты без стенда. Здесь только поля документа и применение.

⚠️ РАСКЛАДКА СЧИТАЕТСЯ ПО КАЖДОЙ СТРОКЕ ОТДЕЛЬНО. Технолог кладёт на один лист
детали из разных позиций и за счёт этого выигрывает ещё. Наш расчёт так не
умеет и не должен: он даёт верхнюю оценку закупки, а экономия — работа цеха.
Поэтому сумма листов по строкам всегда не меньше того, что выйдет у технолога.
"""

from odoo import api, fields, models

from .sheeting import DEFAULT_KERF_MM, plan_sheets


class MetalSpecLayout(models.Model):
    _inherit = "pmk.metal.spec"

    # Габарит листа, из которого считаем. Три значения — те, что заведены
    # характеристикой номенклатуры; 1500×6000 стоит по умолчанию, потому что
    # цены в прайсах заведены именно на него.
    layout_sheet_size = fields.Selection(
        [("1500x6000", "1500 × 6000"),
         ("1500x3000", "1500 × 3000"),
         ("1000x4000", "1000 × 4000")],
        "Габарит листа", default="1500x6000",
        help="Из какого листа считаем раскладку. По умолчанию 1500×6000 — "
             "на него заведены цены поставщика.")

    layout_kerf_mm = fields.Float(
        "Ширина реза, мм", default=DEFAULT_KERF_MM, digits=(4, 2),
        help="Сколько металла съедает рез. Лазер — 0,2 мм; у плазмы больше, "
             "у гильотины реза нет вовсе.")

    def _layout_sheet_dims(self):
        """Габарит листа числами: (ширина, длина) в миллиметрах."""
        self.ensure_one()
        raw = (self.layout_sheet_size or "1500x6000").split("x")
        return float(raw[0]), float(raw[1])

    def action_draft_layout(self):
        """Посчитать черновую раскладку по всем листовым строкам."""
        for spec in self:
            width, length = spec._layout_sheet_dims()
            lines = spec.mapped("product_ids.line_sheet_ids")
            for line in lines:
                line._apply_draft_layout(width, length, spec.layout_kerf_mm)
        return True


class MetalSpecLineLayout(models.Model):
    _inherit = "pmk.metal.spec.line"

    layout_per_sheet = fields.Integer(
        "Заготовок в листе", readonly=True,
        help="Сколько таких заготовок помещается в один лист при укладке "
             "рядами. Технолог обычно кладёт плотнее.")
    layout_sheets = fields.Integer(
        "Листов купить", readonly=True,
        help="Сколько листов нужно под это количество заготовок во всём "
             "изделии. Неполный лист считается целым: купить половину нельзя.")
    layout_scheme = fields.Char(
        "Схема укладки", readonly=True,
        help="Как легли заготовки: рядов на лист и поворот. «+ полосой» — "
             "остаток листа отрезан полосой и заполнен поперёк.")
    layout_state = fields.Selection(
        [("none", "Не считалась"),
         ("ok", "Посчитана"),
         ("no_size", "Нет габарита детали"),
         ("no_qty", "Нет количества"),
         ("too_big", "Деталь больше листа"),
         ("exact", "Деталь в размер листа")],
        "Состояние раскладки", default="none", readonly=True)
    layout_utilization_pct = fields.Float(
        "Использование по раскладке, %", readonly=True, digits=(5, 1),
        help="Площадь нужных заготовок к площади купленных листов. "
             "На малом заказе доля низкая честно: лист покупается целиком.")

    def _apply_draft_layout(self, width, length, kerf_mm):
        """Посчитать раскладку одной строки и записать результат."""
        self.ensure_one()
        if self.calc_mode != "sheet":
            return

        # Количество заготовок — на ВСЕ изделия: qty в строке задано на одно
        # изделие, а лист покупается под заказ целиком.
        total_qty = (self.qty or 0) * (self.product_id.qty or 0)
        plan = plan_sheets(
            width, length, self.a_mm, self.b_mm, total_qty,
            kerf_mm=kerf_mm or DEFAULT_KERF_MM)

        self.layout_per_sheet = plan["per_sheet"]
        self.layout_sheets = plan["sheets"]
        self.layout_scheme = plan["scheme"]
        self.layout_state = plan["state"]
        self.layout_utilization_pct = plan["utilization_pct"]

    @api.onchange("a_mm", "b_mm", "qty", "sheet_id")
    def _onchange_layout_stale(self):
        """Размеры поменяли — прежняя раскладка больше не про эту деталь.

        Гасим её, а не пересчитываем молча: число листов, посчитанное под
        другие размеры, опаснее отсутствующего — на него уже посмотрели и
        поверили.
        """
        for line in self:
            if line.layout_state != "none":
                line.layout_state = "none"
                line.layout_scheme = False
                line.layout_per_sheet = 0
                line.layout_sheets = 0
                line.layout_utilization_pct = 0.0
