# -*- coding: utf-8 -*-
"""Вкладка «Металлоизделия» — сводка изделий всех калькуляторов (20.10.2026)."""
import json

from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged

SNAPSHOT = json.dumps({"start": {"x": 0, "y": 0},
                       "segs": [{"len": 85, "dir": 0}, {"len": 61, "dir": 90}, {"len": 20, "dir": 180}]})


@tagged("post_install", "-at_install")
class TestSpecSummary(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест сводки)"})
        cls.angle = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест сводки)", "gost": "ГОСТ",
            "size_label": "63x4", "mass_per_meter": 3.9})
        Sheet = cls.env["pmk.metal.sheet"]
        cls.zinc065 = Sheet.search([("sheet_type", "=", "Оцинкованный"), ("thickness_mm", "=", 0.65)], limit=1) \
            or Sheet.create({"sheet_type": "Оцинкованный", "thickness_mm": 0.65, "gost": "ГОСТ 14918-2020",
                             "mass_per_sqm": 5.1})
        cls.dobor_coating = cls.env["pmk.dobor.coating"].create({
            "name": "RAL 8017 (тест сводки)", "ral_code": "8017", "hex_color": "#45322e"})

    def _spec(self):
        spec = self.env["pmk.metal.spec"].create({
            "note": "Сводка",
            "cat_dobor": True, "cat_vent": True,
            "product_ids": [
                Command.create({"name": "Ограждение", "qty": 3, "price_customer_unit": 1000, "line_ids": [
                    Command.create({"detail_name": "Стойка", "calc_mode": "linear",
                                    "profile_id": self.angle.id, "length_mm": 1000, "qty": 2})]}),
                Command.create({"name": "Решётка типовая", "qty": 10, "price_customer_unit": 250}),
            ],
        })
        dobor = spec.dobor_order_ids[:1] or self.env["pmk.dobor.order"].create({"spec_id": spec.id})
        dobor.write({"line_ids": [Command.create({
            "title": "Отлив", "coating_id": self.dobor_coating.id, "sheet_id": self.zinc065.id,
            "plank_length": 2000, "qty": 40, "price_unit": 640, "profile_snapshot_json": SNAPSHOT})]})
        vent = spec.vent_order_ids[:1] or self.env["pmk.vent.hood.order"].create({"spec_id": spec.id})
        vent.write({"line_ids": [Command.create({
            "width": 750, "length": 4000, "qty": 2, "price_unit": 3900,
            "coating_id": self.env.ref("pmk_calc.coating_zinc").id})]})
        spec.invalidate_recordset()
        return spec

    def test_rows(self):
        spec = self._spec()
        summary = spec.pmk_summary
        by_source = {}
        for row in summary["rows"]:
            by_source.setdefault(row["source"], []).append(row)
        self.assertEqual(sorted(by_source), ["dobor", "manual", "metal", "vent"])
        metal = by_source["metal"][0]
        self.assertEqual((metal["name"], metal["qty"], metal["total"]), ("Ограждение", 3, 3000))
        self.assertEqual(metal["details"][0]["name"], "Стойка")
        self.assertEqual((metal["details"][0]["qty"], metal["details"][0]["qty_total"]), (2, 6))
        self.assertAlmostEqual(metal["details"][0]["weight"], 7.8, places=2)
        manual = by_source["manual"][0]
        self.assertEqual((manual["details"], manual["total"]), ([], 2500))
        dobor = by_source["dobor"][0]
        self.assertEqual((dobor["qty"], dobor["total"]), (40, 25600))
        self.assertIn("RAL 8017", dobor["dobor"]["coating"])
        self.assertGreater(dobor["dobor"]["developed"], 0)
        vent = by_source["vent"][0]
        self.assertEqual((vent["qty"], vent["total"]), (2, 7800))
        self.assertTrue(vent["vent"]["parts"], "Заготовки зонта — из спецификации калькулятора.")
        self.assertIn("Заклёпки", [p["name"] for p in vent["vent"]["parts"]])
        self.assertEqual(summary["total"], 3000 + 2500 + 25600 + 7800)
        self.assertEqual(summary["unpriced"], 0)

    def test_draft_category_not_in_summary(self):
        """Категория выключена — «черновик, в расчёт не входит»: в сводке её нет."""
        spec = self._spec()
        spec.write({"cat_dobor": False, "cat_vent": False})
        self.assertEqual({r["source"] for r in spec.pmk_summary["rows"]}, {"metal", "manual"})
        spec.cat_metal = False
        self.assertEqual(spec.pmk_summary["rows"], [])

    def test_view(self):
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_views([(False, "form")])["views"]["form"]["arch"])
        pages = [p.get("name") for p in arch.iter("page") if p.getparent().tag == "notebook"
                 and p.getparent().getparent().tag == "sheet"]
        self.assertEqual(pages[:2], ["pmk_summary", "composition"], "Сводка — первой, перед «Конструкциями».")
        composition = arch.xpath("//page[@name='composition']")[0]
        self.assertEqual(composition.get("string"), "Конструкции")
        self.assertEqual(arch.xpath("//page[@name='pmk_summary']")[0].get("string"), "Металлоизделия")
        self.assertTrue(arch.xpath("//field[@name='pmk_summary'][@widget='pmk_spec_summary']"))
