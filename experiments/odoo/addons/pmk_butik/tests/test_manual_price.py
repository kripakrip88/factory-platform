# -*- coding: utf-8 -*-
"""№314: цена металла вручную, когда позиции нет в прайсах (Голубенко 20.10, Антон 22.10.2026).

Уголок 200×20: 60 кг/м, в прайсах нет. Вписали 90 000 ₽/т → 90 ₽/кг → 5 400 ₽/м; деталь 2 м —
10 800 ₽ металла. Появился прайс 3 000 ₽/м — после «Перечитать цены» берётся он.
"""
from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestManualPrice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест №314)"})
        cls.tmpl = cls.env["product.template"].create({"name": "Уголок 200×20 (тест №314)"})
        cls.bare = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест №314)", "gost": "ГОСТ тест",
            "size_label": "200×20", "mass_per_meter": 60.0, "product_tmpl_id": cls.tmpl.id})
        cls.Spec = cls.env["pmk.metal.spec"].with_context(mail_create_nolog=True, mail_create_nosubscribe=True)

    def _spec(self):
        spec = self.Spec.create({"product_ids": [Command.create({
            "name": "Рама", "qty": 1, "line_ids": [Command.create({
                "calc_mode": "linear", "detail_name": "Балка", "profile_id": self.bare.id,
                "length_mm": 2000.0, "qty": 1})]})]})
        return spec, spec.product_ids.line_ids

    def test_manual_counts_and_price_list_wins(self):
        spec, line = self._spec()
        self.assertEqual(line.price_state, "no_price")
        self.assertEqual(spec.no_price_count, 1)
        line.pmk_manual_price_ton = 90000
        self.assertEqual(line.price_state, "manual")
        self.assertAlmostEqual(line.price_unit, 5400.0, places=2)
        self.assertAlmostEqual(line.cost_clean_one, 10800.0, places=2)
        self.assertEqual(spec.no_price_count, 0, "Ручная цена — не «нет цены».")
        self.assertTrue((line.price_compare_note or "").startswith("вручную"), line.price_compare_note)
        self.assertAlmostEqual(spec.total_cost_fact, 10800.0, places=2)
        # Появилась позиция в прайсе — прайс главнее ручной.
        partner = self.env["res.partner"].create({"name": "Поставщик (тест №314)", "is_company": True})
        self.env["product.supplierinfo"].create({"partner_id": partner.id, "product_tmpl_id": self.tmpl.id,
                                                 "price": 3000.0, "date_start": "2020-01-01"})
        spec.action_refresh_prices()
        self.assertEqual(line.price_state, "ok")
        self.assertAlmostEqual(line.price_unit, 3000.0, places=2)
        # Стёрли ручную при отсутствии прайса — снова «нет цены».
        spec2, line2 = self._spec()
        self.env["product.supplierinfo"].search([("product_tmpl_id", "=", self.tmpl.id)]).unlink()
        line2.pmk_manual_price_ton = 50000
        line2.pmk_manual_price_ton = 0
        self.assertEqual(line2.price_state, "no_price")

    def test_grid_cell_and_hint(self):
        spec, line = self._spec()
        row = next(r for r in spec.konstr_rows()["rows"] if r["kind"] == "detail")
        self.assertTrue(row["can_manual"] and row["no_price"])
        self.assertFalse(row["manual_hint"])
        spec.konstr_save_row(row["id"], {"metal_ton": "95 000"})
        self.assertEqual((line.price_state, line.pmk_manual_price_ton), ("manual", 95000))
        row = next(r for r in spec.konstr_rows()["rows"] if r["kind"] == "detail")
        self.assertEqual((row["metal_ton"], row["manual"], row["can_manual"]), (95000, True, True))
        # Другой расчёт с той же позицией — подсказка со ссылкой на первый.
        other, other_line = self._spec()
        hint = next(r for r in other.konstr_rows()["rows"] if r["kind"] == "detail")["manual_hint"]
        self.assertEqual((hint["price"], hint["spec_id"]), (95000, spec.id))
        self.assertEqual(other_line.price_state, "no_price", "Сама не подставляется.")

    def test_save_prices_and_history(self):
        """«Сохранить цены» пачкой; каждая правка — в историю расчёта: было → стало (22.10.2026)."""
        spec, line = self._spec()
        key = next(r for r in spec.konstr_rows()["rows"] if r["kind"] == "detail")["id"]
        spec.konstr_save_prices({key: "9 800"})
        spec.konstr_save_prices({key: "98000"})
        spec.konstr_save_prices({key: ""})
        self.assertEqual(line.price_state, "no_price")
        notes = [m.body for m in spec.message_ids if "цен" in (m.body or "")]
        text = " | ".join(str(n) for n in notes)
        self.assertIn("цена вручную 9 800 ₽/т", text)
        self.assertIn("было 9 800 → стало 98 000 ₽/т", text)
        self.assertIn("стёрта", text)
        self.assertIn("Балка", text)
