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
        self.assertFalse(dobor.exists(), "выключили — пустой черновик удалён")
        spec.cat_dobor = True
        self.assertEqual(len(spec.dobor_order_ids), 1, "включили снова — новый черновик, не два")

    def test_toggle_off_keeps_filled_document(self):
        """Случайно выключили категорию — позиции не пропадают (Антон 12.10)."""
        spec = self.env["pmk.metal.spec"].create({"cat_vent": True})
        ral = self.env.ref("pmk_calc.coating_ral8017")
        vent = spec.vent_order_ids
        vent.write({"line_ids": [(0, 0, {"width": 500, "length": 1000, "qty": 2, "coating_id": ral.id})]})
        spec.cat_vent = False
        self.assertTrue(vent.exists(), "документ с позициями не удаляется")
        self.assertEqual(vent.spec_id, spec, "и остаётся привязанным к расчёту")
        self.assertFalse(spec._pmk_buy_rows(), "но в металл выключенная категория не входит")
        spec.cat_vent = True
        self.assertEqual(spec.vent_order_ids, vent, "включили — вернулся тот же документ")
        self.assertEqual(len(vent.line_ids), 1)

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

    def test_metal_tab_dobor_rows(self):
        """«Металл»: раскрой доборки расчёта — строкой «что купить»."""
        import json
        from odoo import Command
        spec = self.env["pmk.metal.spec"].create({"cat_dobor": True, "cat_metal": False})
        sheet = self.env["pmk.metal.sheet"].create({"sheet_type": "Оцинкованный", "thickness_mm": 0.7,
                                                    "gost": "ГОСТ 14918-2020 (тест металла)", "mass_per_sqm": 5.5})
        coat = self.env["pmk.dobor.coating"].create({"name": "RAL 9999 (тест металла)", "ral_code": "9999"})
        spec.dobor_order_ids.write({"line_ids": [Command.create({
            "title": "Планка", "coating_id": coat.id, "sheet_id": sheet.id, "plank_length": 2500.0, "qty": 10,
            "profile_snapshot_json": json.dumps({"start": {"x": 0, "y": 0},
                                                 "segs": [{"len": 150, "dir": 0}, {"len": 100, "dir": 90}]})})]})
        rows = spec._pmk_buy_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], spec.dobor_order_ids.name)
        self.assertIn("1250 × 2500", rows[0]["amount"])
        self.assertGreater(rows[0]["kg"], 0)
        html = str(spec.metal_total_html)
        self.assertIn("RAL 9999 (тест металла)", html)
        self.assertIn("Итого", html)

    def test_archive_documents(self):
        """Демо-данные — в архив (Антон 12.10): расчёт, доборка и зонты архивируются и
        возвращаются; в поиске — фильтр «Архив»."""
        spec = self.env["pmk.metal.spec"].create({"cat_dobor": True, "cat_vent": True})
        for rec in (spec, spec.dobor_order_ids, spec.vent_order_ids):
            rec.action_archive()
            self.assertFalse(rec.active)
            self.assertFalse(rec.search([("id", "=", rec.id)]), "архив не виден в списке")
            rec.action_unarchive()
            self.assertTrue(rec.active)
        for xmlid in ("pmk_calc.view_metal_spec_search", "pmk_calc.view_dobor_order_search",
                      "pmk_calc.view_vent_hood_order_search"):
            self.assertIn('name="pmk_archived"', self.env.ref(xmlid).arch)

    def test_move_products_to_calculators(self):
        """Изделия → доборка / вентзонты переключателем и кнопкой, и обратно (13.10.2026)."""
        from odoo.addons.pmk_calc.models import spec_move as sm
        self.assertEqual(sm.parse_length("Отлив оконный RAL 8017, L=2000"), 2000)
        self.assertEqual(sm.parse_size("Зонт вш 500х1000"), (500, 1000))
        self.assertEqual(sm.move_hint("Планка угла наружного"), "dobor")
        self.assertEqual(sm.move_hint("Зонт вш 500х1000"), "vent")
        spec = self.env["pmk.metal.spec"].create({"product_ids": [
            (0, 0, {"name": "Отлив оконный RAL 8017, L=2000", "qty": 12}),
            (0, 0, {"name": "Зонт вш 500х1000, RAL 8017", "qty": 11}),
            (0, 0, {"name": "Закладная деталь Зд3", "qty": 40})]})
        dobor_p, vent_p, keep = spec.product_ids.sorted("id")
        self.assertEqual((dobor_p.pmk_move_hint, vent_p.pmk_move_hint, keep.pmk_move_hint), ("dobor", "vent", False))
        dobor_p.pmk_pick = True
        self.assertEqual(spec.pmk_pick_count, 1)
        spec.action_pmk_pick_to_dobor()
        self.assertTrue(spec.cat_dobor)
        line = spec.dobor_order_ids.line_ids
        self.assertEqual((line.title, line.plank_length, line.qty, line.coating_id.ral_code),
                         ("Отлив оконный RAL 8017, L=2000", 2000.0, 12, "8017"))
        self.assertNotIn(dobor_p.exists(), spec.product_ids)
        vent_p.pmk_pick = True
        spec.action_pmk_pick_to_vent()
        hood = spec.vent_order_ids.line_ids
        self.assertEqual((hood.width, hood.length, hood.qty, hood.coating_id.ral_code), (500, 1000, 11, "8017"))
        self.assertEqual(spec.product_ids, keep)
        hood.action_pmk_back_to_metal()
        self.assertEqual(len(spec.product_ids), 2)
        self.assertFalse(spec.vent_order_ids.line_ids)

    def test_copy_keeps_calculators(self):
        """Копия расчёта (и технический расчёт) — с копиями доборки и зонтов, не пустыми."""
        spec = self.env["pmk.metal.spec"].create({"cat_dobor": True})
        spec.dobor_order_ids.write({"line_ids": [(0, 0, {"title": "Капельник", "plank_length": 2500, "qty": 6})]})
        copy = spec.copy()
        self.assertEqual(len(copy.dobor_order_ids), 1)
        self.assertNotEqual(copy.dobor_order_ids, spec.dobor_order_ids)
        self.assertEqual(copy.dobor_order_ids.line_ids.title, "Капельник")
