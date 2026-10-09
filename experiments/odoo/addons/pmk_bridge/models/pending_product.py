# -*- coding: utf-8 -*-
"""Карточка товара позиции, принятой в справочник (шаг З-10).

Позиция «на разнос» (pmk_calc, metal_pending.py) карточки товара не имеет:
пока её не разнесли, это черновик инженера, и плодить номенклатуру по каждой
опечатке нельзя. Цены у неё поэтому нет — мост считает строку «Нет карточки
товара», она в «Нет цены» расчёта: сигнал «в городе нет», не ошибка.

«Привязать к существующей» — карточка не нужна: детали встают на позицию,
у которой карточка уже есть.

«Принять в справочник» — позиция становится обычной, и ей заводится
карточка, как у 753 позиций, залитых scripts/load_products.py:
  • имя «<позиция> <стандарт>», артикул — тем же генератором (sku.py); не
    разобрался или занят — «PND-…-<id>» (артикул латиницей, без столкновений);
  • категория — по виду (Двутавр, Лист рифлёный, Болты…), неизвестный вид —
    общая «Металлопрокат» / «Лист» / «Метизы»;
  • единица — метр у проката, штука у листа и метиза; склад и партии — как у
    залитых (consu + is_storable, партия у проката и листа);
  • вес — на единственный вариант: масса метра, масса листа 1500×6000
    (масса м² × 9 м² — на этот габарит заведены цены, мина шага 57 не
    трогается), масса штуки;
  • внешние идентификаторы pmk_calc.<ключ> и pmk_bridge.product_<ключ>
    (noupdate) — по ним загрузчик прайсов (tools/load_prices.py,
    reference_from_db) находит позицию и карточку.
Характеристики (марка стали, габарит листа) не вешаются: порядок их
навешивания у залитых карточек хрупкий (scripts/load_products.py, «ПОРЯДОК
ДЕЙСТВИЙ»), добавит администратор в карточке, если понадобятся. Цен у
новой карточки нет — снабженец заведёт прайс; до тех пор «нет цены».
"""
import logging

from odoo import models

from . import sku as sku_gen

_logger = logging.getLogger(__name__)

PARENT_CATEG = {
    "pmk.metal.profile": "pmk_bridge.categ_rolled",
    "pmk.metal.sheet": "pmk_bridge.categ_sheet",
    "pmk.metal.fastener": "pmk_bridge.categ_hw",
}
UOM = {
    "pmk.metal.profile": "uom.product_uom_meter",
    "pmk.metal.sheet": "uom.product_uom_unit",
    "pmk.metal.fastener": "uom.product_uom_unit",
}
TRACKING = {
    "pmk.metal.profile": "lot",
    "pmk.metal.sheet": "lot",
    "pmk.metal.fastener": "none",
}
KEY_PREFIX = {
    "pmk.metal.profile": "profile_z10_",
    "pmk.metal.sheet": "sheet_z10_",
    "pmk.metal.fastener": "fastener_z10_",
}
FALLBACK_SKU = {
    "pmk.metal.profile": "PND-PRF",
    "pmk.metal.sheet": "PND-LST",
    "pmk.metal.fastener": "PND-MTZ",
}
# Габарит листа, на который заведены цены (как DEFAULT_SIZE заявки на металл).
DEFAULT_SHEET_AREA_M2 = 1.5 * 6.0


class MetalPendingProduct(models.AbstractModel):
    _inherit = "pmk.metal.pending.mixin"

    def _pmk_after_accept(self):
        result = super()._pmk_after_accept()
        for rec in self:
            if "product_tmpl_id" in rec._fields and not rec.product_tmpl_id:
                rec._pmk_create_product_card()
        return result

    # ─── Карточка ───────────────────────────────────────────────────────
    def _pmk_card_sku_and_categ(self):
        """(артикул или None, xml-id категории) — тем же правилом, что
        загрузчик (scripts/load_products.py, build_plan)."""
        self.ensure_one()
        try:
            if self._name == "pmk.metal.profile":
                code = sku_gen.profile_sku(self.profile_type, self.size_label)
                categ = "pmk_bridge.categ_rolled_%s" % sku_gen.PROFILE_PREFIX[
                    self.profile_type].lower()
            elif self._name == "pmk.metal.sheet":
                code = sku_gen.sheet_sku(self.sheet_type, self.thickness_mm, self.size_label)
                categ = "pmk_bridge.categ_sheet_%s" % sku_gen.SHEET_PREFIX[
                    self.sheet_type].split("-")[1].lower()
            else:
                code = sku_gen.fastener_sku(self.fastener_type, self.size_label)
                categ = "pmk_bridge.categ_hw_%s" % sku_gen.FASTENER_KIND[
                    self.fastener_type].lower()
        except (sku_gen.SkuError, KeyError) as exc:
            _logger.info("pmk_bridge: артикул позиции %s %s не разобран (%s)",
                         self._name, self.id, exc)
            return None, PARENT_CATEG[self._name]
        return code, categ

    def _pmk_card_vals(self):
        self.ensure_one()
        code, categ_xmlid = self._pmk_card_sku_and_categ()
        Product = self.env["product.product"].sudo().with_context(active_test=False)
        if not code or Product.search_count([("default_code", "=", code)]):
            code = "%s-%s" % (FALLBACK_SKU[self._name], self.id)
        categ = (self.env.ref(categ_xmlid, raise_if_not_found=False)
                 or self.env.ref(PARENT_CATEG[self._name], raise_if_not_found=False))
        uom = self.env.ref(UOM[self._name])
        if self._name == "pmk.metal.fastener":
            name = ("%s %s" % (self.name, self.gost)).strip() if self.gost else self.name
        else:
            name = "%s %s" % (self.display_name, self.gost)
        vals = {
            "name": name,
            "type": "consu",
            "is_storable": True,
            "tracking": TRACKING[self._name],
            "uom_id": uom.id,
            "purchase_ok": True,
            "sale_ok": True,
        }
        if categ:
            vals["categ_id"] = categ.id
        return vals, code

    def _pmk_card_weight(self):
        self.ensure_one()
        if self._name == "pmk.metal.sheet":
            return (self.mass_per_sqm or 0.0) * DEFAULT_SHEET_AREA_M2
        return self._pmk_unit_mass()

    def _pmk_create_product_card(self):
        """Завести карточку товара и связать с позицией (поле и xml-id)."""
        self.ensure_one()
        vals, code = self._pmk_card_vals()
        tmpl = self.env["product.template"].sudo().create(vals)
        variant = tmpl.product_variant_id
        # Артикул и вес — на единственный вариант: у шаблона это зеркала
        # варианта (load_products.py, «ВЕС ЖИВЁТ НА ВАРИАНТЕ»).
        variant.write({"default_code": code, "weight": self._pmk_card_weight()})
        self.sudo().product_tmpl_id = tmpl
        key = "%s%s" % (KEY_PREFIX[self._name], self.id)
        data = self.env["ir.model.data"].sudo()
        if not self.get_external_id().get(self.id):
            data.create({"module": "pmk_calc", "name": key, "model": self._name,
                         "res_id": self.id, "noupdate": True})
        if not data.search_count([("module", "=", "pmk_bridge"), ("name", "=", "product_%s" % key)]):
            # noupdate — обязательно: карточки моста в файлах данных не лежат,
            # без флага обновление модуля сочло бы их сиротами и удалило.
            data.create({"module": "pmk_bridge", "name": "product_%s" % key,
                         "model": "product.template", "res_id": tmpl.id, "noupdate": True})
        return tmpl
