# -*- coding: utf-8 -*-
"""Состав металлоизделия колодца — как детали изделия в «Конструкциях» и состав опоры.

Калькулятор заполняет состав по альбому (строки с auto_key): стойки, ступени, пластины,
фланцы, патрубки, шпильки. Металл — цена за тонну по прайсам (прокат или лист, из
которого режем); покупное — цену вписывают. Строку можно поправить — она помечается
edited и при пересчёте изделия не перезаписывается; можно добавить свою.
"""
import re

from odoo import api, fields, models


class KolodecPart(models.Model):
    _name = "pmk.kolodec.part"
    _description = "Состав металлоизделия колодца"
    _order = "line_id, sequence, id"

    line_id = fields.Many2one("pmk.kolodec.line", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    auto_key = fields.Char("Из альбома", help="Строку заполнил калькулятор (ключ детали).")
    edited = fields.Boolean("Поправлено", help="Правили руками — пересчёт изделия её не перезапишет.")
    name = fields.Char("Наименование")
    metal = fields.Boolean("Металл", help="Цена за тонну по прайсам; иначе — покупное, цена за шт.")
    material = fields.Char("Материал", help="Позиция справочника, по которой взята цена (JSON).")
    thickness = fields.Float("Лист, мм", digits=(6, 1), help="Металл из листа: толщина.")
    qty = fields.Float("На 1 изделие", digits=(10, 2), default=1.0)
    unit_mass = fields.Float("Масса ед., кг", digits=(10, 3))
    price_unit = fields.Float("Цена за шт", digits=(12, 2))
    price_ton = fields.Float("Цена за т", digits=(12, 0), help="Металл — по тоннам.")
    mass = fields.Float("Масса на изделие, кг", compute="_compute_cost", store=True, digits=(10, 3))
    cost = fields.Float("Стоимость на изделие", compute="_compute_cost", store=True, digits=(12, 2))

    @api.depends("qty", "unit_mass", "price_unit", "price_ton", "metal")
    def _compute_cost(self):
        for part in self:
            part.mass = part.qty * part.unit_mass
            if part.metal:
                part.cost = part.mass * part.price_ton / 1000.0
            else:
                part.cost = part.qty * part.price_unit

    def _pmk_is_metal(self):
        self.ensure_one()
        return self.metal

    def _pmk_user_write(self, vals):
        """Правка из таблицы: строка из альбома становится «поправленной»."""
        vals = dict(vals)
        if self.auto_key:
            vals["edited"] = True
        self.write(vals)


def parse_part(text):
    """«шпилька м16х190 8шт 45» → своя строка состава (покупная, цена за шт). «лист 8 0,8кг» —
    металл: толщина и масса, цена за тонну. Без разбора — как есть."""
    src = (text or "").strip()
    low = src.lower().replace("ё", "е")
    vals = {"name": src}
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*шт", low)
    if m:
        vals["qty"] = float(m.group(1).replace(",", "."))
        low = low[:m.start()] + " " + low[m.end():]
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*кг", low)
    if m:
        vals["unit_mass"] = float(m.group(1).replace(",", "."))
        low = low[:m.start()] + " " + low[m.end():]
    m = re.search(r"лист\w*\s*(\d+(?:[.,]\d+)?)", low)
    if m:
        vals["thickness"] = float(m.group(1).replace(",", "."))
        vals["metal"] = True
        low = low[:m.start()] + " " + low[m.end():]
    m = re.search(r"(?:цена\s*|по\s*)?(\d+(?:[.,]\d+)?)\s*(?:₽|р\b|руб)", low) or \
        re.search(r"(?<![мm\d.,×x-])(\d+(?:[.,]\d+)?)\s*$", low.strip())
    if m:
        price = float(m.group(1).replace(",", "."))
        vals["price_ton" if vals.get("metal") else "price_unit"] = price
    return vals
