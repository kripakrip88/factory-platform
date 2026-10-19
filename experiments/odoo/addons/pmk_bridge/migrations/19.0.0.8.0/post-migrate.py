# -*- coding: utf-8 -*-
"""19.0.0.8.0 — лист в м², габарит — единица-«упаковка» (№309, 19.10.2026).

Было: карточка листа в штуках, вес = лист 1500×6000 (масса м² × 9), габарит —
характеристика варианта (Ст3сп, 1500x6000), цена поставщика «за штуку».
Стало: карточка в м², вес = кг/м², габарит — единица «Лист 1500×6000» (9 м²)
в цене поставщика и в строке закупки, вариант — только марка.

Порядок важен, каждый шаг проверен на копии:
1. запомнить габарит цен и строк закупки (из варианта / ключа заявки);
2. сменить единицу карточки. Odoo при этом ПЕРЕПИСЫВАЕТ единицу строк закупки
   и движений на м² без пересчёта (stock/purchase _update_uom) — «5 листов»
   стали бы «5 м²»; поэтому шаг 3;
3. строкам закупки, движениям и ценам поставщика — единица габарита (SQL:
   количество и цена «за лист» не меняются, пересчёт ядра не будим);
4. вес = кг/м², на карточку — только габариты из прайсов и закупок;
5. характеристику «Габарит листа» снять в два хода: сперва убрать значение
   из варианта, потом строку. «В лоб» Odoo удаляет/архивирует вариант
   вместе с ценами (замер на копии 19.10);
6. строки расчётов: цена единицы хранится числом «за лист» — делим на площадь
   габарита её цены; цена за кг/т и суммы не меняются (проверка в журнале).
"""
import logging
import re

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)
DEFAULT_SIZE = "1500x6000"
KEY_SIZE_RE = re.compile(r":(\d+x\d+)$")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False})
    Uom = env["uom.uom"]
    sqm = Uom._pmk_sqm()
    unit = env.ref("uom.product_uom_unit")
    attr = env.ref("pmk_bridge.attr_sheet_size", raise_if_not_found=False)
    sheets = env["pmk.metal.sheet"].search([("product_tmpl_id", "!=", False)])
    tmpls = sheets.product_tmpl_id.filtered(lambda t: t.uom_id == unit)
    if not tmpls:
        _logger.info("pmk_bridge 19.0.0.8.0: карточек листа в штуках нет — пропуск")
        return
    mass = {s.product_tmpl_id.id: s.mass_per_sqm or 0.0 for s in sheets}

    def variant_size(variant):
        names = variant.product_template_attribute_value_ids.filtered(
            lambda v: attr and v.attribute_id == attr).mapped("name")
        return names[0] if names else DEFAULT_SIZE

    # ── 1. габарит цен и строк закупки, пока он ещё в вариантах
    seller_size = {}
    for info in env["product.supplierinfo"].search([("product_tmpl_id", "in", tmpls.ids)]):
        seller_size[info.id] = variant_size(info.product_id) if info.product_id else DEFAULT_SIZE
    po_size = {}
    variants = tmpls.with_context(active_test=False).product_variant_ids
    for line in env["purchase.order.line"].search([("product_id", "in", variants.ids)]):
        m = KEY_SIZE_RE.search(line.pmk_request_key or "") if "pmk_request_key" in line._fields else None
        po_size[line.id] = m.group(1) if m else variant_size(line.product_id)
    # строки расчётов: площадь габарита их цены
    spec_lines = env["pmk.metal.spec.line"].search([
        ("calc_mode", "=", "sheet"), ("sheet_id", "in", sheets.filtered(
            lambda s: s.product_tmpl_id in tmpls).ids)])
    before = {l.id: (l.price_unit, l.price_kg, l.cost_fact_total) for l in spec_lines}

    # ── 2. единица карточки
    tmpls.write({"uom_id": sqm.id})
    env.flush_all()

    # ── 3. закупки, движения, цены — в единицу габарита
    for line_id, size in po_size.items():
        uom = Uom._pmk_sheet_uom(size)
        cr.execute("UPDATE purchase_order_line SET product_uom_id=%s WHERE id=%s", (uom.id, line_id))
        cr.execute("UPDATE stock_move SET product_uom=%s WHERE purchase_line_id=%s", (uom.id, line_id))
    for info_id, size in seller_size.items():
        cr.execute("UPDATE product_supplierinfo SET product_uom_id=%s WHERE id=%s",
                   (Uom._pmk_sheet_uom(size).id, info_id))
    env.invalidate_all()

    # ── 4. вес и габариты на карточке
    for tmpl in tmpls:
        kg = mass.get(tmpl.id, 0.0)
        tmpl.product_variant_ids.write({"weight": kg})
        used = {s for i, s in seller_size.items()
                if env["product.supplierinfo"].browse(i).product_tmpl_id == tmpl}
        used |= {s for l, s in po_size.items()
                 if env["purchase.order.line"].browse(l).product_id.product_tmpl_id == tmpl}
        for size in used:
            tmpl._pmk_add_packaging(Uom._pmk_sheet_uom(size))

    # ── 5. характеристика «Габарит листа» — в два хода
    if attr:
        for tmpl in tmpls:
            line = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == attr)
            if not line:
                continue
            for variant in tmpl.with_context(active_test=False).product_variant_ids:
                keep = variant.product_template_attribute_value_ids.filtered(
                    lambda v: v.attribute_line_id != line)
                if keep != variant.product_template_attribute_value_ids:
                    variant.product_template_attribute_value_ids = keep
            line.unlink()
    env.flush_all()
    lost = tmpls.filtered(lambda t: not t.product_variant_ids)
    if lost:
        raise RuntimeError("19.0.0.8.0: у карточек листа пропал вариант: %s" % lost.mapped("name"))

    # ── 6. строки расчётов: цена «за лист» → «за м²»
    fixed, drift = 0, []
    for line in spec_lines:
        size = seller_size.get(line.price_source_id.id) if line.price_source_id else None
        area = Uom._pmk_sheet_uom(size or DEFAULT_SIZE).relative_factor or 9.0
        if line.price_unit or line.price_prev_unit:
            cr.execute("UPDATE pmk_metal_spec_line SET price_unit=price_unit/%s, "
                       "price_prev_unit=price_prev_unit/%s WHERE id=%s", (area, area, line.id))
            fixed += 1
    env.invalidate_all()
    for line in spec_lines:
        unit_was, kg_was, cost_was = before[line.id]
        kg_now = mass.get(line.sheet_id.product_tmpl_id.id, 0.0)
        if line.price_unit and kg_now:
            implied = line.price_unit / kg_now
            if line.price_kg and abs(implied - line.price_kg) / line.price_kg > 0.01:
                drift.append((line.id, round(implied, 2), round(line.price_kg, 2)))
        if abs((line.cost_fact_total or 0.0) - (cost_was or 0.0)) > 0.01:
            drift.append((line.id, "сумма", cost_was, line.cost_fact_total))
    _logger.info("pmk_bridge 19.0.0.8.0: карточек листа в м²: %s; цен: %s; строк закупки: %s; "
                 "строк расчётов: %s (цена за лист → за м²); расхождений: %s",
                 len(tmpls), len(seller_size), len(po_size), fixed, len(drift))
    for item in drift[:30]:
        _logger.warning("pmk_bridge 19.0.0.8.0: расхождение цены/суммы строки расчёта %s", item)
