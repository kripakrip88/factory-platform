# -*- coding: utf-8 -*-
"""Состав опоры — как детали изделия в «Конструкциях» и состав болта (pmk_bolt).

Калькулятор заполняет состав по ОСТ (строки с auto_key): корпус, рёбра, подушки,
полухомуты, болты, гайки, упоры. Металл — лист, цена за тонну по прайсам; болты
и гайки — покупные, цену вписывают. Строку можно поправить — она помечается
edited и при пересчёте опоры не перезаписывается; можно добавить свою.
Себестоимость опоры — сумма состава.
"""
import re

from odoo import api, fields, models

AUTO_KEYS = [("corpus", "Корпус гнутый"), ("bottom", "Дно корпуса"), ("wall", "Стенки корпуса"),
             ("rib", "Ребро"), ("rib_end", "Рёбра торцевые"), ("pad", "Подушки"), ("clamp", "Полухомуты"),
             ("bolt", "Болты"), ("nut", "Гайки"), ("stop", "Упоры")]
BUY_KEYS = ("bolt", "nut")


class OporaPart(models.Model):
    _name = "pmk.opora.part"
    _description = "Состав опоры трубопровода"
    _order = "line_id, sequence, id"

    line_id = fields.Many2one("pmk.opora.line", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    auto_key = fields.Selection(AUTO_KEYS, "Из ОСТ", help="Строку заполнил калькулятор.")
    edited = fields.Boolean("Поправлено", help="Правили руками — пересчёт опоры её не перезапишет.")
    name = fields.Char("Наименование")
    thickness = fields.Float("Лист, мм", digits=(6, 1), help="Металл: толщина листа, из которого деталь.")
    # Заготовка a×b (25.10.2026, вариант 1): в расчёт опора идёт изделием «Конструкций», лист —
    # номенклатурой с размером заготовки (развёртка корпуса, ребро до выреза по трубе).
    a_mm = fields.Float("Заготовка A, мм", digits=(8, 1))
    b_mm = fields.Float("Заготовка B, мм", digits=(8, 1))
    qty = fields.Float("На 1 опору", digits=(10, 2), default=1.0)
    unit_mass = fields.Float("Масса ед., кг", digits=(10, 3))
    price_unit = fields.Float("Цена за шт", digits=(12, 2))
    price_ton = fields.Float("Цена за т", digits=(12, 0), help="Металл — по тоннам.")
    mass = fields.Float("Масса на опору, кг", compute="_compute_cost", store=True, digits=(10, 3))
    cost = fields.Float("Стоимость на опору", compute="_compute_cost", store=True, digits=(12, 2))

    @api.depends("qty", "unit_mass", "price_unit", "price_ton", "auto_key", "thickness")
    def _compute_cost(self):
        for part in self:
            part.mass = part.qty * part.unit_mass
            if part._pmk_is_metal():
                part.cost = part.mass * part.price_ton / 1000.0
            else:
                part.cost = part.qty * part.price_unit

    def _pmk_is_metal(self):
        self.ensure_one()
        if self.auto_key:
            return self.auto_key not in BUY_KEYS
        return bool(self.thickness)

    def _pmk_user_write(self, vals):
        """Правка из таблицы: строка из ОСТ становится «поправленной»."""
        vals = dict(vals)
        if self.auto_key:
            vals["edited"] = True
        self.write(vals)


def parse_part(text):
    """«болт м20х60 2шт 25» → своя строка состава (покупная, цена за шт). «лист 10 1,5кг» —
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
        low = low[:m.start()] + " " + low[m.end():]
    m = re.search(r"(?:цена\s*|по\s*)?(\d+(?:[.,]\d+)?)\s*(?:₽|р\b|руб)", low) or \
        re.search(r"(?<![мm\d.,×x-])(\d+(?:[.,]\d+)?)\s*$", low.strip())
    if m:
        price = float(m.group(1).replace(",", "."))
        vals["price_ton" if vals.get("thickness") else "price_unit"] = price
    return vals
