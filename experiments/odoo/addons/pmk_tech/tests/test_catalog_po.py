# -*- coding: utf-8 -*-
"""Заявка на металл: строка из каталога материалов (26.10.2026)."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


def card_of(env, fastener):
    """Карточка метиза: на чистой тестовой базе мост их не заводит (нет ни одной)."""
    if not fastener.product_tmpl_id:
        fastener.product_tmpl_id = env["product.template"].create({
            "name": fastener.name, "type": "consu", "uom_id": env.ref("uom.product_uom_unit").id})
    return fastener.product_tmpl_id


@tagged("post_install", "-at_install")
class TestCatalogPo(TransactionCase):

    def test_add_from_catalog(self):
        partner = self.env["res.partner"].create({"name": "Поставщик (тест каталога)", "is_company": True})
        order = self.env["purchase.order"].create({"partner_id": partner.id})
        bolt = self.env.ref("pmk_calc.fast2_bolt_20_60_88_zinc")
        card_of(self.env, bolt)
        order.pmk_catalog_add("fastener:%d" % bolt.id)
        self.assertEqual(order.order_line.product_id.product_tmpl_id, bolt.product_tmpl_id)
        self.assertEqual(order.order_line.product_qty, 1.0)
        pending = self.env["pmk.metal.fastener"].with_context(default_pmk_pending=True).create({
            "pmk_pending_name": "Болт М20×60 нерж (тест)", "weight_kg": 0.2})
        order.pmk_catalog_add("fastener:%d" % pending.id)
        line = order.order_line[-1:]
        self.assertTrue(line.pmk_pending)
        self.assertIn("нерж", line.name)
        order.button_confirm()
        with self.assertRaises(UserError):
            order.pmk_catalog_add("fastener:%d" % bolt.id)
