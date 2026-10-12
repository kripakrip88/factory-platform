# -*- coding: utf-8 -*-
"""Цена клиенту у доборок и вентзонтов — вручную (Антон 12.10.2026).

«Давай пока что цены вручную иметь возможность проставлять, логику расценки сделаем
позже доработкой калькуляторов». Цена за штуку — в строке, сумма строки и итог заказа
считаются. По ним счёт собирает строки из категорий расчёта (pmk_orders).
"""
from odoo import api, fields, models


class DoborOrderLinePrice(models.Model):
    _inherit = "pmk.dobor.order.line"

    price_unit = fields.Float("Цена за шт, ₽", digits=(12, 2),
                              help="Цена клиенту за одну планку — вручную. Расценка калькулятором — позже.")
    price_total = fields.Float("Сумма, ₽", compute="_compute_price_total", store=True, digits=(12, 2))

    @api.depends("price_unit", "qty")
    def _compute_price_total(self):
        for line in self:
            line.price_total = line.price_unit * line.qty


class DoborOrderPrice(models.Model):
    _inherit = "pmk.dobor.order"

    amount_total = fields.Float("Сумма, ₽", compute="_compute_amount_total", store=True, digits=(12, 2))
    has_unpriced = fields.Boolean("Есть позиции без цены", compute="_compute_amount_total", store=True)

    @api.depends("line_ids.price_total", "line_ids.price_unit")
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped("price_total"))
            order.has_unpriced = any(not l.price_unit for l in order.line_ids)


class VentHoodPrice(models.Model):
    _inherit = "pmk.vent.hood"

    price_unit = fields.Float("Цена за шт, ₽", digits=(12, 2),
                              help="Цена клиенту за один зонт — вручную. Расценка калькулятором — позже.")
    price_total = fields.Float("Сумма, ₽", compute="_compute_price_total", store=True, digits=(12, 2))

    @api.depends("price_unit", "qty")
    def _compute_price_total(self):
        for line in self:
            line.price_total = line.price_unit * line.qty


class VentHoodOrderPrice(models.Model):
    _inherit = "pmk.vent.hood.order"

    amount_total = fields.Float("Сумма, ₽", compute="_compute_amount_total", store=True, digits=(12, 2))
    has_unpriced = fields.Boolean("Есть размеры без цены", compute="_compute_amount_total", store=True)

    @api.depends("line_ids.price_total", "line_ids.price_unit")
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped("price_total"))
            order.has_unpriced = any(not l.price_unit for l in order.line_ids)
