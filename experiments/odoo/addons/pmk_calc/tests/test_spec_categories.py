# -*- coding: utf-8 -*-
"""Категории изделий в расчёте (12.10.2026): включили — черновик калькулятора, выключили — удалён."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpecCategories(TransactionCase):

    def test_toggle_creates_and_removes_drafts(self):
        partner = self.env["res.partner"].create({"name": "Клиент категорий"})
        spec = self.env["pmk.metal.spec"].create({"partner_id": partner.id, "cat_dobor": True,
                                                  "note": "Ангар"})
        self.assertTrue(spec.cat_metal, "металлоизделия — по умолчанию")
        self.assertEqual(len(spec.dobor_order_ids), 1)
        dobor = spec.dobor_order_ids
        self.assertEqual((dobor.partner_id, dobor.customer, dobor.spec_id), (partner, "Ангар", spec))
        self.assertFalse(spec.vent_order_ids)

        spec.cat_vent = True
        self.assertEqual(len(spec.vent_order_ids), 1)
        self.assertEqual(spec.vent_order_ids.partner_id, partner)

        other = self.env["res.partner"].create({"name": "Другой клиент"})
        spec.partner_id = other
        self.assertEqual(dobor.partner_id, other, "клиент расчёта — клиент его калькуляторов")

        spec.cat_dobor = False
        self.assertFalse(dobor.exists(), "выключили — черновик удалён (демо-данные)")
        spec.cat_dobor = True
        self.assertEqual(len(spec.dobor_order_ids), 1, "включили снова — новый черновик, не два")

    def test_child_lines_and_open(self):
        spec = self.env["pmk.metal.spec"].create({"cat_vent": True})
        ral = self.env.ref("pmk_calc.coating_ral8017")
        spec.vent_order_ids.write({"line_ids": [(0, 0, {"width": 500, "length": 1000, "qty": 2,
                                                        "coating_id": ral.id, "price_unit": 1500})]})
        self.assertEqual(len(spec.vent_line_ids), 1)
        self.assertEqual(spec.vent_line_ids.price_total, 3000)
        self.assertEqual(spec.vent_order_ids.amount_total, 3000)
        action = spec.action_open_vent()
        self.assertEqual((action["res_model"], action["res_id"]), ("pmk.vent.hood.order", spec.vent_order_ids.id))
        self.assertFalse(spec.action_open_dobor(), "доборки нет — нечего открыть")
