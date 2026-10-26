# -*- coding: utf-8 -*-
"""Счета на проверке — пересчитать цены и ставку НДС (26.10.2026).

Лист: текущая цена бралась за м², новая — за лист габарита («+755 %» вместо −2 %), масса листа —
справочника, а не поставщика. Ставка НДС — 0 там, где в счёте только сумма НДС. Сопоставление
строк (в том числе выбранное вручную) не трогаем — только цену. Ненайденные строки («позиция
не найдена» — оцинковка до исправления разборщика) сопоставляем заново."""
from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_supplier_invoice.models.recognize import _vat_rate


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for inv in env["pmk.supplier.invoice"].search([("state", "=", "review")]):
        rate = _vat_rate(inv.vat_rate, inv.amount_total, inv.amount_vat)
        if rate != inv.vat_rate:
            inv.vat_rate = rate
        inv.line_ids.filtered(lambda l: l.kind == "metal" and l.product_tmpl_id)._pmk_price()
        inv.line_ids.filtered(lambda l: l.kind == "metal" and l.match_state == "none")._pmk_match()
