# -*- coding: utf-8 -*-
"""Вид документа в заголовке расчёта: «Расчёт КП СМ-… от …» / «Технический
расчёт СМ-… от …» (Антон 15.10.2026)."""
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpecTitleKind(TransactionCase):

    def test_title_names_kind(self):
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_view(view_type="form")["arch"])
        h1 = arch.xpath("//div[hasclass('oe_title')]/h1")[0]
        kinds = {span.text: span.get("invisible") for span in h1.xpath("./span[hasclass('pmk-spec-title__kind')]")}
        self.assertEqual(kinds["Расчёт КП"], "not id or pmk_kind == 'tech'")
        self.assertEqual(kinds["Технический расчёт"], "not id or pmk_kind != 'tech'")
        order = [child.get("name") or (child.text or "").strip() for child in h1]
        self.assertLess(order.index("Технический расчёт"), order.index("name"), "вид — перед номером")
