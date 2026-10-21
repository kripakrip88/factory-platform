# -*- coding: utf-8 -*-
"""Состав болта — как детали изделия в «Конструкциях» (Антон 21.10.2026: «болт
фундаментный должен быть составом вида как у металлоизделия, отдельно круг гайки
шайбы плиты … иногда просят дополнительные гайки … это нужно скорректировать»).

Калькулятор заполняет состав по ГОСТ (строки с auto_key): круг (шпилька),
гайки, шайба, плита (тип 2), работа (резьба, гиб, проточка). Строку можно
поправить — она помечается edited и при пересчёте болта не перезаписывается;
можно добавить свою («гайка м30 калён 2шт 45»). Себестоимость болта — сумма
состава. Цена круга — за тонну, остальное — за штуку.
"""
import re

from odoo import api, fields, models

from ..tools import gost

AUTO_KEYS = [("stud", "Круг (шпилька)"), ("nut", "Гайки"), ("washer", "Шайба"), ("plate", "Плита"),
             ("work", "Работа")]
NUT_KIND_TEXT = {"plain": "", "hardened": "калёные", "special": "спецсталь"}


class BoltPart(models.Model):
    _name = "pmk.bolt.part"
    _description = "Состав фундаментного болта"
    _order = "line_id, sequence, id"

    line_id = fields.Many2one("pmk.bolt.line", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    auto_key = fields.Selection(AUTO_KEYS, "Из ГОСТ", help="Строку заполнил калькулятор.")
    edited = fields.Boolean("Поправлено", help="Правили руками — пересчёт болта её не перезапишет.")
    name = fields.Char("Наименование")
    qty = fields.Float("На 1 болт", digits=(10, 2), default=1.0)
    unit_mass = fields.Float("Масса ед., кг", digits=(10, 3))
    price_unit = fields.Float("Цена за шт", digits=(12, 2))
    price_ton = fields.Float("Цена за т", digits=(12, 0), help="Только у круга: металл по тоннам.")
    mass = fields.Float("Масса на болт, кг", compute="_compute_cost", store=True, digits=(10, 3))
    cost = fields.Float("Стоимость на болт", compute="_compute_cost", store=True, digits=(12, 2))

    @api.depends("qty", "unit_mass", "price_unit", "price_ton", "auto_key")
    def _compute_cost(self):
        for part in self:
            part.mass = part.qty * part.unit_mass
            if part.auto_key == "stud":
                part.cost = part.mass * part.price_ton / 1000.0
            else:
                part.cost = part.qty * part.price_unit

    def _pmk_user_write(self, vals):
        """Правка из таблицы: строка из ГОСТ становится «поправленной»."""
        vals = dict(vals)
        if self.auto_key:
            vals["edited"] = True
        self.write(vals)


def parse_part(text):
    """«гайка м30 калён 2шт 45» → поля строки состава (своя строка). Без разбора — как есть."""
    src = (text or "").strip()
    low = src.lower().replace("ё", "е")
    vals = {"name": src}
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*шт", low)
    if m:
        vals["qty"] = float(m.group(1).replace(",", "."))
        low = low[:m.start()] + " " + low[m.end():]
    m = re.search(r"(?:цена\s*|по\s*)?(\d+(?:[.,]\d+)?)\s*(?:₽|р\b|руб)", low) or \
        re.search(r"(?<![мm\d.,-])(\d+(?:[.,]\d+)?)\s*$", low.strip())
    if m:
        vals["price_unit"] = float(m.group(1).replace(",", "."))
    d = re.search(r"[мm]\s*-?\s*(\d{2})(?!\d)", low)
    d = int(d.group(1)) if d else 0
    if d in gost.SIZES:
        if "гайк" in low:
            vals["unit_mass"] = gost.NUT_KG[d]
        elif "шайб" in low:
            vals["unit_mass"] = gost.SIZES[d]["w"]
    return vals
