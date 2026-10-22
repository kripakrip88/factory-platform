# -*- coding: utf-8 -*-
"""Номер счёта из Odoo — продолжение нумерации МС в её виде, «01233» (22.10.2026)."""
from datetime import datetime

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMsNumber(TransactionCase):

    def setUp(self):
        super().setUp()
        self.client = self.env["res.partner"].create({"name": "ООО «Нумерация»", "is_company": True})
        self.now = fields.Datetime.now()

    def _ms(self, name, when=None):
        return self.env["sale.order"].create({
            "name": name, "partner_id": self.client.id, "pmk_ms_id": "ms-num-" + name,
            "date_order": when or self.now})

    def test_continues_ms(self):
        Order = self.env["sale.order"]
        base = int(Order._pmk_next_ms_number())
        self._ms("%05d" % (base + 40))
        self._ms("%05d" % (base + 900), when=datetime(self.now.year - 1, 6, 1))  # прошлый год не считается
        self._ms("000059 (заявка №48)")
        first = Order.create({"partner_id": self.client.id})
        self.assertEqual(first.name, "%05d" % (base + 41))
        second = Order.create({"partner_id": self.client.id})
        self.assertEqual(second.name, "%05d" % (base + 42), "Следующий — после нашего.")
        self.assertEqual(self._ms("%05d" % (base + 50)).name, "%05d" % (base + 50),
                         "Счёт МС приходит со своим номером.")
        named = Order.create({"partner_id": self.client.id, "name": "Свой номер"})
        self.assertEqual(named.name, "Свой номер")
