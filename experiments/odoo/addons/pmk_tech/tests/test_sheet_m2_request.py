# -*- coding: utf-8 -*-
"""Заявка на металл: лист — листами габарита, карточка в м² (№309, 19.10.2026).

Гонять ТОЛЬКО на одноразовой базе. Ловим: строка закупки листа идёт в
единице «Лист WxL» своего габарита, а не в м² карточки («5 листов» не
превращаются в «5 м²»), цена — за лист, единица попадает на карточку, ручная
цена (мина шага 57) у карточки в м² не нужна. Карточка ещё в штуках — по-старому.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSheetM2Request(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sqm = cls.env.ref("uom.product_uom_square_meter")
        cls.tmpl = cls.env["product.template"].create({
            "name": "Лист 4 мм (тест м² заявки)", "uom_id": cls.sqm.id, "weight": 31.4})
        cls.old_tmpl = cls.env["product.template"].create({
            "name": "Лист 4 мм в штуках (тест м² заявки)", "weight": 282.6})
        cls.Spec = cls.env["pmk.metal.spec"]

    def _row(self, product, size):
        return {"mode": "sheet", "product": product, "size": size, "label": "лист",
                "qty": 5.0, "price": 14130.0, "key": "sheet:%s:%s" % (product.product_tmpl_id.id, size)}

    def test_line_in_gabarit_unit(self):
        variant = self.tmpl.product_variant_id
        vals = self.Spec._pmk_request_line_vals(self._row(variant, "1500x3000"))
        u3000 = self.env["uom.uom"]._pmk_sheet_uom("1500x3000")
        self.assertEqual(vals["product_uom_id"], u3000.id)
        self.assertEqual(vals["product_qty"], 5.0, "5 листов, не 5 м²")
        self.assertEqual(vals["price_unit"], 14130.0, "цена за лист")
        self.assertIn(u3000, self.tmpl.uom_ids, "габарит лёг на карточку")

    def test_legacy_card_keeps_unit(self):
        variant = self.old_tmpl.product_variant_id
        vals = self.Spec._pmk_request_line_vals(self._row(variant, "1500x3000"))
        self.assertEqual(vals["product_uom_id"], self.old_tmpl.uom_id.id)
        self.assertFalse(self.old_tmpl.uom_ids)
