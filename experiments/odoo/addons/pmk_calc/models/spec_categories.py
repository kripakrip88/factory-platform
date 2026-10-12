# -*- coding: utf-8 -*-
"""Категории изделий в расчёте (решение Антона 12.10.2026).

Расчёт (СМ-…) — общий документ заказа. В шапке — категории: металлоизделия (живут в
самом расчёте, вкладка «Металлоизделия»), доборные элементы, вентзонты (отдельные
документы калькуляторов ДОБ-… / ВЗ-…, привязанные к расчёту полем «Расчёт»). Включили
категорию — создаётся черновик в калькуляторе (клиент, объект; сделку переносит
pmk_deal); выключили — документ с позициями становится черновиком расчёта: вкладка видна
с пометкой «черновик», а металл и счёт его не берут; включили — снова в расчёте (Антон
12.10: «если случайно нажать и отключить… придётся всё забивать с нуля»; «черновик — не
идёт в расчёт, активен — идёт»). Пустой черновик при выключении удаляется.
Позже — другие категории тем же приёмом.
"""
from odoo import api, fields, models

CHILDREN = (
    # (флаг категории, модель калькулятора, поле-список документов в расчёте)
    ("cat_dobor", "pmk.dobor.order", "dobor_order_ids"),
    ("cat_vent", "pmk.vent.hood.order", "vent_order_ids"),
)


class DoborOrderSpec(models.Model):
    _inherit = "pmk.dobor.order"

    spec_id = fields.Many2one("pmk.metal.spec", "Расчёт", index=True, copy=False, ondelete="cascade",
                              help="Расчёт заказа, к которому относится эта доборка (категория «Доборные "
                                   "элементы»). Пусто — доборка сама по себе.")


class VentHoodOrderSpec(models.Model):
    _inherit = "pmk.vent.hood.order"

    spec_id = fields.Many2one("pmk.metal.spec", "Расчёт", index=True, copy=False, ondelete="cascade",
                              help="Расчёт заказа, к которому относятся эти вентзонты (категория "
                                   "«Вентзонты»). Пусто — заказ сам по себе.")


class MetalSpecCategories(models.Model):
    _inherit = "pmk.metal.spec"

    cat_metal = fields.Boolean("Металлоизделия", default=True,
                               help="Изделия по чертежу — состав здесь же, во вкладке «Металлоизделия».")
    cat_dobor = fields.Boolean("Доборные элементы", help="Включено — доборка в расчёте. Выключено — черновик: позиции целы, в расчёт не входят.")
    cat_vent = fields.Boolean("Вентзонты", help="Включено — вентзонты в расчёте. Выключено — черновик: размеры целы, в расчёт не входят.")
    dobor_order_ids = fields.One2many("pmk.dobor.order", "spec_id", "Доборки")
    vent_order_ids = fields.One2many("pmk.vent.hood.order", "spec_id", "Вентзонты")
    dobor_line_ids = fields.Many2many("pmk.dobor.order.line", compute="_compute_child_lines",
                                      string="Позиции доборки")
    vent_line_ids = fields.Many2many("pmk.vent.hood", compute="_compute_child_lines",
                                     string="Размеры вентзонтов")

    @api.depends("dobor_order_ids.line_ids", "vent_order_ids.line_ids")
    def _compute_child_lines(self):
        for spec in self:
            spec.dobor_line_ids = spec.dobor_order_ids.line_ids
            spec.vent_line_ids = spec.vent_order_ids.line_ids

    # ------------------------------------------------------------ черновики
    def _pmk_child_vals(self, model):
        """Что переносится в черновик калькулятора. pmk_deal добавляет сделку."""
        self.ensure_one()
        return {"spec_id": self.id, "partner_id": self.partner_id.id or False,
                "customer": (self.note or "")[:200] or False}

    def _pmk_sync_children(self):
        for spec in self:
            for flag, model, field in CHILDREN:
                docs = spec[field]
                if spec[flag] and not docs:
                    self.env[model].create(spec._pmk_child_vals(model))
                elif not spec[flag] and docs:
                    # Пустой черновик — мусор; документ с позициями — работа, его не трогаем.
                    docs.filtered(lambda d: not d.line_ids).unlink()

    @api.model_create_multi
    def create(self, vals_list):
        specs = super().create(vals_list)
        specs.filtered(lambda s: s.cat_dobor or s.cat_vent)._pmk_sync_children()
        return specs

    def write(self, vals):
        res = super().write(vals)
        if {"cat_dobor", "cat_vent"} & set(vals):
            self._pmk_sync_children()
        if "partner_id" in vals:
            # Клиент расчёта — клиент его калькуляторов.
            for spec in self:
                spec.dobor_order_ids.write({"partner_id": spec.partner_id.id})
                spec.vent_order_ids.write({"partner_id": spec.partner_id.id})
        return res

    def _pmk_open_child(self, field):
        self.ensure_one()
        doc = self[field][:1]
        if not doc:
            return False
        return {"type": "ir.actions.act_window", "res_model": doc._name, "res_id": doc.id,
                "views": [(False, "form")], "target": "current"}

    def action_open_dobor(self):
        return self._pmk_open_child("dobor_order_ids")

    def action_open_vent(self):
        return self._pmk_open_child("vent_order_ids")
