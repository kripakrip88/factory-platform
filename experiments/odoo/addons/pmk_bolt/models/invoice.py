# -*- coding: utf-8 -*-
"""Болты в счёте (Антон 21.10.2026): один путь — болты → расчёт → счёт.

- Счёт из расчёта берёт болты с ценой (категория «Фундаментные болты» включена):
  полное название по ГОСТ, количество, цена за шт. Без цены — в «без цены клиенту».
- Черновик счёта идёт за болтами: поменяли болт, количество, цену, состав —
  строки черновика пересобираются (как у доборки и зонтов, pmk_orders
  category_invoice.py).
- «Создать ▾ → Фундаментные болты» в счёте: расчёт есть — в нём включаем болты и
  открываем; нет — расчёт из строк счёта (как «Создать → Расчёт»), уже с болтами.
"""
from odoo import _, api, fields, models

from odoo.addons.pmk_orders.models import spec_xlsx

# «Расчёт (Excel)», лист «Изделия»: раздел строки болта.
spec_xlsx.SRC.setdefault("bolt", "Фундаментные болты")

BOLT_FIELDS = frozenset({"price_unit", "qty", "sequence", "bolt_type", "diameter", "length", "thread_len",
                         "steel", "nut_kind", "markup_pct"})


class SaleOrderLineBolt(models.Model):
    _inherit = "sale.order.line"

    pmk_bolt_line_id = fields.Many2one("pmk.bolt.line", "Болт расчёта", index=True, copy=False,
                                       ondelete="set null")


class SaleOrderBolt(models.Model):
    _inherit = "sale.order"

    @api.model
    def _pmk_invoice_items(self, spec):
        items = super()._pmk_invoice_items(spec)
        if "cat_bolt" in spec._fields and spec.cat_bolt:
            for line in spec.bolt_calc_ids.line_ids.filtered(lambda l: l.name and l.price_unit):
                items.append({
                    "key": ("b", line.id), "name": line.name, "qty": line.qty, "price": line.price_unit,
                    "sequence": 3000 + line.sequence, "link": {"pmk_bolt_line_id": line.id}})
        return items

    @api.model
    def _pmk_unpriced_names(self, spec):
        names = super()._pmk_unpriced_names(spec)
        if "cat_bolt" in spec._fields and spec.cat_bolt:
            names += spec.bolt_calc_ids.line_ids.filtered(lambda l: l.name and not l.price_unit).mapped("short_name")
        return names

    def _pmk_line_key(self, line):
        if line.pmk_bolt_line_id:
            return ("b", line.pmk_bolt_line_id.id)
        return super()._pmk_line_key(line)

    # ─── «Создать ▾ → Фундаментные болты» ───────────────────────────────
    def pmk_doc_menu(self):
        menu = super().pmk_doc_menu()
        menu["create"].insert(1, {"key": "bolts", "label": _("Фундаментные болты"), "icon": "fa-cog",
                                  "method": "action_pmk_doc_bolts"})
        return menu

    def action_pmk_doc_bolts(self):
        self.ensure_one()
        if not self.pmk_spec_id:
            self.action_pmk_doc_spec()  # расчёт из строк счёта — тем же путём, что «Создать → Расчёт»
        spec = self.pmk_spec_id
        spec.cat_bolt = True
        action = self.action_open_spec()
        action.setdefault("context", {})
        return action


class BoltLineInvoice(models.Model):
    """Черновик счёта идёт за болтами расчёта."""
    _inherit = "pmk.bolt.line"

    def _pmk_specs(self):
        return self.mapped("calc_id.spec_id")

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._pmk_specs()._pmk_sync_draft_invoices()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if BOLT_FIELDS & set(vals):
            self._pmk_specs()._pmk_sync_draft_invoices()
        return res

    def unlink(self):
        specs = self._pmk_specs()
        res = super().unlink()
        specs._pmk_sync_draft_invoices()
        return res


class BoltPartInvoice(models.Model):
    """Состав меняет себестоимость → цену болта → строку черновика счёта."""
    _inherit = "pmk.bolt.part"

    def write(self, vals):
        res = super().write(vals)
        if {"qty", "price_unit", "price_ton"} & set(vals):
            self.mapped("line_id.calc_id.spec_id")._pmk_sync_draft_invoices()
        return res
