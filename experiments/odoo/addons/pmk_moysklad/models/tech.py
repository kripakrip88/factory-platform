# -*- coding: utf-8 -*-
"""Технический расчёт по счёту из МоегоСклада (Антон 12.10.2026: «менеджер создал
счёт в МоёмСкладе — увидеть в Odoo и сделать по нему внутренний расчёт»).

У такого счёта нет расчёта КП — кнопка «Технический расчёт» (pmk_tech) заводит
пустой расчёт. Здесь его изделия заполняются строками счёта: название, количество
и цена клиенту. Состав (металл, доборки, зонты) инженер набирает сам.
"""
from odoo import api, models


class MetalSpecMs(models.Model):
    _inherit = "pmk.metal.spec"

    @api.model
    def _pmk_create_tech(self, order):
        tech = super()._pmk_create_tech(order)
        if order.pmk_ms_id and not order.pmk_spec_id and not tech.product_ids:
            products = []
            for seq, line in enumerate(order.order_line.filtered(lambda l: not l.display_type), 1):
                qty = line.product_uom_qty
                whole = qty > 0 and float(qty).is_integer()
                name = line.name if whole else "%s — %s" % (line.name, ("%g" % qty).replace(".", ","))
                products.append((0, 0, {
                    "sequence": seq,
                    "name": name[:250],
                    "qty": int(qty) if whole else 1,
                    "price_customer_unit": line.price_unit * (1 - (line.discount or 0) / 100.0)
                    if whole else line.price_total,
                }))
            if products:
                tech.write({"product_ids": products,
                            "note": tech.note or order.pmk_ms_object or order.partner_id.name})
        return tech
