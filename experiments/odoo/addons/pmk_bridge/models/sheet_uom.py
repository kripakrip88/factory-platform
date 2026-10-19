# -*- coding: utf-8 -*-
"""Лист в м², габарит — единица-«упаковка» (№309, 19.10.2026).

Лист 1500×6000 — это 9 м² той же карточки (data/uom_sheet.xml). Здесь — одна
дверь «габарит ↔ единица» для расчёта, загрузчика цен и заявки на металл: ключ
габарита тот же, что у строки расчёта (layout_sheet_size, «1500x6000»).
"""
from odoo import api, fields, models

SQM_XMLID = "uom.product_uom_square_meter"
SHEET_UOM_XMLID = {
    "1250x2500": "pmk_bridge.uom_sheet_1250x2500",
    "1500x3000": "pmk_bridge.uom_sheet_1500x3000",
    "1500x6000": "pmk_bridge.uom_sheet_1500x6000",
    "2000x6000": "pmk_bridge.uom_sheet_2000x6000",
    "1000x4000": "pmk_bridge.uom_sheet_1000x4000",
}


class UomSheet(models.Model):
    _inherit = "uom.uom"

    @api.model
    def _pmk_sqm(self):
        return self.env.ref(SQM_XMLID, raise_if_not_found=False) or self.browse()

    @api.model
    def _pmk_sheet_uom(self, size):
        """Единица «Лист WxL» по ключу габарита; нет такого — пусто."""
        xmlid = SHEET_UOM_XMLID.get((size or "").replace("×", "x").replace(" ", ""))
        return (self.env.ref(xmlid, raise_if_not_found=False) if xmlid else None) or self.browse()

    @api.model
    def _pmk_sheet_sizes(self):
        """{id единицы: ключ габарита}. env.ref кэширован (ormcache), лишних
        запросов на строку списка нет."""
        out = {}
        for size, xmlid in SHEET_UOM_XMLID.items():
            uom = self.env.ref(xmlid, raise_if_not_found=False)
            if uom:
                out[uom.id] = size
        return out

    def _pmk_sheet_size(self):
        """Ключ габарита («1500x6000») единицы листа; не лист — пустая строка."""
        self.ensure_one()
        return self._pmk_sheet_sizes().get(self.id, "")


class ProductTemplateSheetUom(models.Model):
    _inherit = "product.template"

    # Признак для видов: колонка «Ед.» у цен и «Габариты» в карточке — только
    # у листа в м². Не хранится: единицу карточки правят, признак не устареет.
    pmk_is_sqm = fields.Boolean("Лист в м²", compute="_compute_pmk_is_sqm")

    @api.depends("uom_id")
    def _compute_pmk_is_sqm(self):
        sqm = self.env["uom.uom"]._pmk_sqm()
        for tmpl in self:
            tmpl.pmk_is_sqm = bool(sqm) and tmpl.uom_id == sqm

    def _pmk_is_sqm(self):
        """Карточка считается в м² (лист после №309)."""
        self.ensure_one()
        sqm = self.env["uom.uom"]._pmk_sqm()
        return bool(sqm) and self.uom_id == sqm

    def _pmk_add_packaging(self, uom):
        """Дописать единицу-габарит карточке, если её там нет (только нужные:
        «не перехламить систему», Антон 19.10)."""
        for tmpl in self:
            if uom and uom != tmpl.uom_id and uom not in tmpl.uom_ids:
                tmpl.sudo().uom_ids = [(4, uom.id)]
