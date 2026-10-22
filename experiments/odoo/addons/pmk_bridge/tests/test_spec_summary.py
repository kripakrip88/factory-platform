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

    def test_header_all_categories(self):
        """Шапка — по всем категориям (22.10.2026): цена клиенту и вес с доборкой и зонтами,
        маржа — только по позициям с себестоимостью."""
        spec = self._spec()
        products = sum(spec.product_ids.mapped("price_customer_total"))
        self.assertEqual(products, 3000 + 2500)
        self.assertAlmostEqual(spec.price_customer_total, products + 25600 + 7800, places=2)
        self.assertAlmostEqual(spec.price_uncosted, 25600 + 7800, places=2)
        self.assertAlmostEqual(spec.cost_all_total, spec.total_cost_fact, places=2)
        self.assertAlmostEqual(spec.margin_amount, products - spec.total_cost_fact, places=2)
        weight = (sum(spec.product_ids.mapped("weight_total")) + sum(spec.dobor_line_ids.mapped("weight_total"))
                  + sum(spec.vent_line_ids.mapped("total_mass_net_kg")))
        self.assertGreater(sum(spec.dobor_line_ids.mapped("weight_total")), 0)
        self.assertAlmostEqual(spec.total_weight, weight, places=2)
        self.assertEqual(spec.total_products, 2 + 1 + 1)
        self.assertEqual(spec.customer_unpriced_count, 0)
        # Без цены клиенту у доборки — итог меньше, пометка «без цены».
        spec.dobor_line_ids.price_unit = 0
        self.assertAlmostEqual(spec.price_customer_total, products + 7800, places=2)
        self.assertEqual(spec.customer_unpriced_count, 1)
        # Категория выключена — в шапку не входит.
        spec.cat_vent = False
        self.assertAlmostEqual(spec.price_customer_total, products, places=2)
        self.assertAlmostEqual(spec.total_weight, sum(spec.product_ids.mapped("weight_total"))
                               + sum(spec.dobor_line_ids.mapped("weight_total")), places=2)

    def _zinc(self, thick):
        Sheet = self.env["pmk.metal.sheet"]
        return Sheet.search([("sheet_type", "=", "Оцинкованный"), ("thickness_mm", "=", thick)], limit=1) \
            or Sheet.create({"sheet_type": "Оцинкованный", "thickness_mm": thick, "gost": "ГОСТ 14918-2020",
                             "mass_per_sqm": thick * 7.85})

    def test_entry_routes_lines(self):
        """Ввод в сводке (22.10.2026): строка сама уходит в свою категорию."""
        self._zinc(0.45)
        self._zinc(0.65)
        spec = self.env["pmk.metal.spec"].create({"note": "Ввод строками"})
        res = spec.pmk_summary_add(["дэ 2500мм 0,45мм рал8017 10шт", "зонт 500х1000 0,65 8017 2шт",
                                    "Ферма Ф-2 3шт", "зонт 0,65 8017 2шт", "  "])
        self.assertEqual(res["added"], {"Доборка": 1, "Вентзонты": 1, "Конструкции": 1})
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("размера шахты", res["errors"][0])
        self.assertTrue(spec.cat_dobor and spec.cat_vent and spec.cat_metal)
        line = spec.dobor_line_ids
        self.assertEqual((line.plank_length, line.qty, line.sheet_id.thickness_mm, line.coating_id.ral_code),
                         (2500, 10, 0.45, "8017"))
        self.assertIn("RAL 8017 (", line.title)
        hood = spec.vent_line_ids
        self.assertEqual((hood.width, hood.length, hood.qty, hood.thickness, hood.coating_id.ral_code),
                         (500, 1000, 2, 0.65, "8017"))
        product = spec.product_ids
        self.assertEqual((product.name, product.qty), ("Ферма Ф-2", 3))
        self.assertEqual({r["source"] for r in spec.pmk_summary["rows"]}, {"dobor", "vent", "manual"})
        # Цвет словом из справочника (Антон 22.10.2026: «вино» → RAL 3005).
        wine = self.env["pmk.dobor.coating"].search([("ral_code", "=", "3005")], limit=1) \
            or self.env["pmk.dobor.coating"].create({"name": "RAL 3005 Вино", "ral_code": "3005"})
        res = spec.pmk_summary_add(["дэ 2000мм 0,45мм вино 5шт", "зонт 500х1000 0,65 винный 1шт"])
        self.assertEqual(res["added"], {"Доборка": 1, "Вентзонты": 1}, res["errors"])
        self.assertEqual(spec.dobor_line_ids.filtered(lambda l: l.qty == 5).coating_id, wine)
        self.assertEqual(spec.vent_line_ids.filtered(lambda h: h.qty == 1).coating_id, wine)
        # Без цвета у зонта и без толщины у доборки — не заводим, ошибка словами.
        res = spec.pmk_summary_add(["зонт 500х1000 0,65 2шт", "дэ 2000мм 10шт"])
        self.assertEqual(res["added"], {})
        self.assertEqual(len(res["errors"]), 2)
        self.assertEqual(len(spec.vent_line_ids), 2)

    def test_entry_move(self):
        """«Перенести в»: строка без своей работы переносится; не разобралась — остаётся на месте."""
        self._zinc(0.65)
        spec = self.env["pmk.metal.spec"].create({"note": "Перенос"})
        spec.pmk_summary_add(["Отлив 2000 3шт", "зонт 500х1000 0,65 8017 2шт"])
        product, hood = spec.product_ids, spec.vent_line_ids
        res = spec.pmk_summary_move("metal-%s" % product.id, "dobor")
        self.assertIn("error", res)
        self.assertTrue(product.exists())
        res = spec.pmk_summary_move("vent-%s" % hood.id, "metal")
        self.assertEqual(res, {"moved": "Конструкции"})
        self.assertFalse(hood.exists())
        moved = spec.product_ids - product
        self.assertEqual((moved.name, moved.qty), ("зонт 500х1000 0,65 8017", 2))
        # Изделие с деталями не переносится.
        spec.product_ids[:1].line_ids = [Command.create({"detail_name": "Стойка", "calc_mode": "linear",
                                                         "profile_id": self.angle.id, "length_mm": 500, "qty": 1})]
        with self.assertRaises(Exception):
            spec.pmk_summary_move("metal-%s" % spec.product_ids[:1].id, "vent")
