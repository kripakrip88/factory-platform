# -*- coding: utf-8 -*-
"""Лист доборки и вентзонта — по цвету (Антон 26.10.2026: «давай сразу сделаем»).

Оцинкованный 0,65 дешевле окрашенного, и с 26.10 у крашеного листа свой вид справочника
«Окрашенный» (своя карточка и цены). Цвет и металл выбираются в строке порознь: поле
«Металл» задаёт ТОЛЩИНУ, а вид листа решает цвет —

    Цинк (покрытие без кода RAL)  → «Лист оцинкованный <толщина>»;
    любой RAL                      → «Лист окрашенный <толщина>»; такой толщины крашеного
                                     в справочнике нет (0,55 / 0,6 / 0,7) — остаётся оцинкованный.

Правило работает на сервере при любой записи (форма, «Бутик», перенос между категориями,
копирование), в форме — сразу при выборе цвета. Масса у обоих видов одна (толщина × 7,85),
вес, раскрой и ведомость не меняются; меняется карточка — и цена листа из прайсов.
"""
from odoo import api, models

PAINTED, ZINC = "Окрашенный", "Оцинкованный"


class MetalSheetCoating(models.Model):
    _inherit = "pmk.metal.sheet"

    def _pmk_for_coating(self, coating):
        """Лист той же толщины под цвет coating (pmk.dobor.coating). Не лист доборки
        (гладкий, рифлёный) или пары нет — сам лист."""
        self.ensure_one()
        if self.sheet_type not in (PAINTED, ZINC) or not coating:
            return self
        want = PAINTED if (coating.ral_code or "").strip() else ZINC
        if self.sheet_type == want:
            return self
        twin = self.search([("sheet_type", "=", want), ("thickness_mm", ">=", self.thickness_mm - 1e-6),
                            ("thickness_mm", "<=", self.thickness_mm + 1e-6)], limit=1)
        return twin or self


class SheetByCoatingMixin(models.AbstractModel):
    """Общее для строки доборки и вентзонта: sheet_id + coating_id."""
    _name = "pmk.sheet.by.coating.mixin"
    _description = "Лист по цвету (доборка, вентзонт)"

    def _pmk_sheet_by_coating(self):
        for rec in self:
            if rec.sheet_id and rec.coating_id:
                sheet = rec.sheet_id._pmk_for_coating(rec.coating_id)
                if sheet != rec.sheet_id:
                    # Второй проход write увидит нужный лист и ничего не запишет.
                    rec.sheet_id = sheet

    @api.onchange("coating_id", "sheet_id")
    def _onchange_pmk_sheet_by_coating(self):
        for rec in self:
            if rec.sheet_id and rec.coating_id:
                rec.sheet_id = rec.sheet_id._pmk_for_coating(rec.coating_id)


class DoborLineSheetByCoating(models.Model):
    _name = "pmk.dobor.order.line"
    _inherit = ["pmk.dobor.order.line", "pmk.sheet.by.coating.mixin"]

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._pmk_sheet_by_coating()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if "coating_id" in vals or "sheet_id" in vals:
            self._pmk_sheet_by_coating()
        return res


class VentHoodSheetByCoating(models.Model):
    _name = "pmk.vent.hood"
    _inherit = ["pmk.vent.hood", "pmk.sheet.by.coating.mixin"]

    @api.model_create_multi
    def create(self, vals_list):
        hoods = super().create(vals_list)
        hoods._pmk_sheet_by_coating()
        return hoods

    def write(self, vals):
        res = super().write(vals)
        if "coating_id" in vals or "sheet_id" in vals:
            self._pmk_sheet_by_coating()
        return res
