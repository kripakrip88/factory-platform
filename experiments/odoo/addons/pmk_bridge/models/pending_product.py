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

from odoo import api, models

from . import sku as sku_gen

_logger = logging.getLogger(__name__)

PARENT_CATEG = {
    "pmk.metal.profile": "pmk_bridge.categ_rolled",
    "pmk.metal.sheet": "pmk_bridge.categ_sheet",
    "pmk.metal.fastener": "pmk_bridge.categ_hw",
}
UOM = {
    "pmk.metal.profile": "uom.product_uom_meter",
    # №309: лист — в м², габарит — единица «Лист WxL» (sheet_uom.py).
    "pmk.metal.sheet": "uom.product_uom_square_meter",
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


class MetalPendingProduct(models.AbstractModel):
    _inherit = "pmk.metal.pending.mixin"

    def _pmk_after_accept(self):
        result = super()._pmk_after_accept()
        for rec in self:
            if "product_tmpl_id" in rec._fields and not rec.product_tmpl_id:
                rec._pmk_create_product_card()
        return result

    @api.model
    def _pmk_cards_for_data_rows(self):
        """Карточки строкам справочника из файла данных, у которых их нет.

        Пополнение справочника 18.10.2026: новые размеры проката приходят
        строками CSV модуля pmk_calc, а карточки первых 665 позиций заводил
        разовый загрузчик (scripts/load_products.py). Вызывается при каждом
        обновлении моста (data/cards_for_data_rows.xml), повторный вызов
        ничего не заводит.

        Только прокат: карточке листа нужны характеристики марки и габарита,
        их ставит загрузчик в строгом порядке («ПОРЯДОК ДЕЙСТВИЙ» в нём).
        На чистой базе, где карточек ещё нет вовсе, не делаем ничего — там
        номенклатуру заводит загрузчик целиком.
        """
        Profile = self.env["pmk.metal.profile"].sudo().with_context(active_test=False)
        if not Profile.search_count([("product_tmpl_id", "!=", False)], limit=1):
            return 0
        return Profile._pmk_cards_create(Profile.search(
            [("product_tmpl_id", "=", False), ("pmk_pending", "=", False)]))

    @api.model
    def _pmk_sheet_cards_for_data_rows(self):
        """Карточки строкам справочника ЛИСТА из файла данных (26.10.2026: оцинковка
        1,2–3 мм — Металлсервис её продаёт, а справочник кончался на 1,0).

        Как у залитых листов (scripts/load_products.py, шаг 5): единица м², строка
        «Марка стали» сначала с ОДНИМ значением Ст3сп — единственный вариант впитывает
        метку и остаётся жив с артикулом, потом полный набор марок (характеристика
        динамическая — вариантов не плодит). Габарит-единицу («Лист 1250×2500») и
        вариант марки прайса (08кп) заводит загрузчик цен при записи."""
        Sheet = self.env["pmk.metal.sheet"].sudo().with_context(active_test=False)
        if not Sheet.search_count([("product_tmpl_id", "!=", False)], limit=1):
            return 0
        rows = Sheet.search([("product_tmpl_id", "=", False), ("pmk_pending", "=", False)])
        count = Sheet._pmk_cards_create(rows)
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)
        seed = self.env.ref("pmk_bridge.attr_grade_st3sp", raise_if_not_found=False)
        if count and attr and seed:
            Line = self.env["product.template.attribute.line"].sudo()
            for tmpl in rows.mapped("product_tmpl_id"):
                if tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == attr):
                    continue
                line = Line.create({"product_tmpl_id": tmpl.id, "attribute_id": attr.id,
                                    "value_ids": [(6, 0, seed.ids)]})
                line.value_ids = [(6, 0, attr.value_ids.ids)]
        return count

    def _pmk_cards_create(self, rows):
        """Завести карточки строкам из файла данных (pmk_calc.*); черновики и
        строки с карточкой пропускаются. Возвращает, сколько заведено."""
        ext = rows.get_external_id()
        rows = rows.filtered(lambda r: not r.product_tmpl_id and not r.pmk_pending
                             and (ext.get(r.id) or "").startswith("pmk_calc."))
        for rec in rows:
            rec._pmk_create_product_card()
        if rows:
            _logger.info("pmk_bridge: заведено карточек по справочнику: %s", len(rows))
        return len(rows)

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
            # №309: карточка листа в м² — вес единицы = кг/м².
            return self.mass_per_sqm or 0.0
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
        # Ключ — имя внешнего идентификатора строки, если он есть: строка из
        # файла данных (pmk_calc.profile_полоса_4x40) получает карточку
        # pmk_bridge.product_profile_полоса_4x40 — по этому правилу её ищет
        # загрузчик цен (tools/load_prices.py, reference_from_db). Принятая
        # новая позиция внешнего идентификатора не имеет — ей заводим свой.
        own = self.get_external_id().get(self.id) or ""
        key = (own.split(".", 1)[1] if own.startswith("pmk_calc.")
               else "%s%s" % (KEY_PREFIX[self._name], self.id))
        data = self.env["ir.model.data"].sudo()
        if not own:
            data.create({"module": "pmk_calc", "name": key, "model": self._name,
                         "res_id": self.id, "noupdate": True})
        if not data.search_count([("module", "=", "pmk_bridge"), ("name", "=", "product_%s" % key)]):
            # noupdate — обязательно: карточки моста в файлах данных не лежат,
            # без флага обновление модуля сочло бы их сиротами и удалило.
            data.create({"module": "pmk_bridge", "name": "product_%s" % key,
                         "model": "product.template", "res_id": tmpl.id, "noupdate": True})
        return tmpl
