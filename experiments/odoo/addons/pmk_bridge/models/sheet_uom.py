# -*- coding: utf-8 -*-
"""Лист в м², габарит — единица-«упаковка» (№309, 19.10.2026).

Лист 1500×6000 — это 9 м² той же карточки (data/uom_sheet.xml). Здесь — одна
дверь «габарит ↔ единица» для расчёта, загрузчика цен и заявки на металл: ключ
габарита тот же, что у строки расчёта (layout_sheet_size, «1500x6000»).
"""
from odoo import api, fields, models

from . import sku as sku_gen

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

    # ─── Марка — вариант (№309, этап 2, 19.10.2026) ──────────────────────
    def _compute_default_code(self):
        """Артикул карточки с несколькими марками — артикул базового варианта.

        Ядро ставит карточке артикул, только пока вариант один: второй вариант
        (марка 09Г2С) обнулял «LST-GL-3» у карточки — в «Номенклатуре» пусто,
        поиск по артикулу её не находил. Берём самый короткий артикул варианта:
        у базового варианта он без хвоста марки («LST-GL-3», а не
        «LST-GL-3-09G2S», sku.variant_sku).
        """
        super()._compute_default_code()
        for tmpl in self:
            if tmpl.default_code or len(tmpl.product_variant_ids) < 2:
                continue
            codes = [c for c in tmpl.product_variant_ids.mapped("default_code") if c]
            if codes:
                tmpl.default_code = min(codes, key=lambda c: (len(c), c))

    def _pmk_grade_variant(self, grade_name, create=False):
        """Вариант карточки с маркой grade_name; create — завести, если нет.

        Значение марки дописывается в строку характеристики (dynamic: ядро
        вариантов само не плодит), вариант — по одной комбинации. Существующие
        варианты не трогаются (замер на копии 19.10: вариант Ст3сп с ценами жив).
        Артикул — артикул карточки + марка (sku.variant_sku), вес — как у базового.
        """
        self.ensure_one()
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)
        Product = self.env["product.product"]
        if not attr:
            return Product
        for variant in self.product_variant_ids:
            names = variant.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_id == attr).mapped("name")
            if grade_name in names:
                return variant
        if not create:
            return Product
        value = attr.value_ids.filtered(lambda v: v.name == grade_name)[:1]
        line = self.attribute_line_ids.filtered(lambda l: l.attribute_id == attr)[:1]
        if not value or not line or len(self.attribute_line_ids) != 1:
            return Product
        base = self.product_variant_ids[:1]
        base_code = self.default_code
        line.sudo().value_ids = [(4, value.id)]
        self.env.flush_all()
        ptav = self.env["product.template.attribute.value"].sudo().search([
            ("attribute_line_id", "=", line.id), ("product_attribute_value_id", "=", value.id)], limit=1)
        variant = self.sudo()._create_product_variant(ptav)
        if variant:
            vals = {"weight": base.weight}
            if base_code:
                vals["default_code"] = sku_gen.variant_sku(base_code, sku_gen.grade_code(grade_name))
            variant.write(vals)
        return variant

    def _pmk_grade_value_exists(self, grade_name):
        """Марка заведена значением характеристики, и у карточки есть её строка —
        вариант можно завести (для отчёта пробного прогона загрузчика)."""
        self.ensure_one()
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)
        return bool(attr and attr.value_ids.filtered(lambda v: v.name == grade_name)
                    and self.attribute_line_ids.filtered(lambda l: l.attribute_id == attr))

