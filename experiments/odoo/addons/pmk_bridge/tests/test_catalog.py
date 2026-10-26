# -*- coding: utf-8 -*-
"""Каталог материалов (26.10.2026): разделы, выборка с фильтрами и ценой, с чего открыть."""
import datetime

from odoo.tests import TransactionCase, tagged


def card_of(env, fastener):
    """Карточка метиза: на чистой тестовой базе мост их не заводит (нет ни одной)."""
    if not fastener.product_tmpl_id:
        fastener.product_tmpl_id = env["product.template"].create({
            "name": fastener.name, "type": "consu", "uom_id": env.ref("uom.product_uom_unit").id})
    return fastener.product_tmpl_id


@tagged("post_install", "-at_install")
class TestCatalog(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Cat = self.env["pmk.metal.catalog"]

    def test_tree_sections(self):
        tree = {s["key"]: s for s in self.Cat.catalog_tree()}
        self.assertEqual(set(tree), {"profile", "sheet", "fastener"})
        self.assertIn("bolt", [k["key"] for k in tree["fastener"]["kinds"]])
        self.assertIn("Окрашенный", [k["key"] for k in tree["sheet"]["kinds"]])
        self.assertEqual([s["key"] for s in self.Cat.catalog_tree(["fastener"])], ["fastener"])

    def test_guess(self):
        g = self.Cat.catalog_guess("болт 20х60")
        self.assertEqual((g["section"], g["kind"]), ("fastener", "bolt"))
        self.assertIn("20х60", g["query"])
        self.assertEqual(self.Cat.catalog_guess("лист 0,65 рал")["section"], "sheet")
        self.assertEqual(self.Cat.catalog_guess("", ["fastener"])["section"], "fastener")

    def test_search_fastener_filters_and_price(self):
        bolt = self.env.ref("pmk_calc.fast2_bolt_20_60_88_black")
        partner = self.env["res.partner"].create({"name": "Поставщик метизов (тест)", "is_company": True})
        card_of(self.env, bolt)
        self.env["product.supplierinfo"].create({
            "partner_id": partner.id, "product_tmpl_id": bolt.product_tmpl_id.id, "price": 52.92,
            "date_start": datetime.date(2026, 10, 1), "product_uom_id": bolt.product_tmpl_id.uom_id.id})
        res = self.Cat.catalog_search("fastener", "bolt", "20х60", "8.8", "black", False)
        keys = [r["key"] for r in res["rows"]]
        self.assertIn("fastener:%d" % bolt.id, keys)
        row = res["rows"][keys.index("fastener:%d" % bolt.id)]
        self.assertEqual((row["price"], row["unit"], row["supplier"]), (52.92, "шт", partner.name))
        self.assertTrue(all("8.8" in r["name"] for r in res["rows"]))
        priced = self.Cat.catalog_search("fastener", "bolt", "20х60", "", "", True)["rows"]
        self.assertEqual([r["key"] for r in priced], ["fastener:%d" % bolt.id], "только с ценой")

    def test_search_sheet_and_profile(self):
        rows = self.Cat.catalog_search("sheet", "Окрашенный", "", "", "", False)["rows"]
        self.assertTrue(rows and all("окрашенный" in r["name"] for r in rows))
        self.assertEqual(rows[0]["unit"], "м²")
        angle = self.Cat.catalog_search("profile", None, "уг 50х5", "", "", False)["rows"]
        self.assertTrue(angle and "50" in angle[0]["name"])
