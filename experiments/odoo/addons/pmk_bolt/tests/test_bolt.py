# -*- coding: utf-8 -*-
"""Калькулятор фундаментных болтов (21.10.2026)."""
from datetime import date

from odoo import Command
from odoo.tests import TransactionCase, tagged

from ..tools import gost


@tagged("post_install", "-at_install")
class TestGost(TransactionCase):

    def test_tables_and_kit(self):
        self.assertEqual(gost.table_mass("1.1", 30, 900), 6.22)
        self.assertEqual(gost.table_mass("2.1", 30, 600), 6.64)
        self.assertEqual(gost.table_mass("2.2", 56, 1000), 38.43)
        self.assertEqual(gost.table_mass("5", 48, 1400), 22.53)
        self.assertIsNone(gost.table_mass("1.1", 30, 950))
        self.assertEqual(gost.check("2.1", 12), "Тип 2.1 делают М16–М48")
        self.assertEqual(gost.check("2.2", 30), "Тип 2.2 делают М56–М90")
        self.assertEqual(gost.check("1.2", 30), "")

    def test_blank_two_diameters_per_bend(self):
        """Антон: «поправка 2 диаметра на гиб» — 1.1 М30×1000: 1000 + 90 − 60."""
        self.assertEqual(gost.blank_mm("1.1", 30, 1000), 1030)
        self.assertEqual(gost.blank_mm("2.1", 30, 600), 600)
        self.assertGreater(gost.blank_mm("1.2", 30, 1000), 1000 + 120 - 60)  # + удлинение отгиба

    def test_formula_mass_close_to_table(self):
        """Длина не из ряда — по формуле; рядом с табличной соседней длиной."""
        formula = gost.mass("1.1", 30, 950)
        self.assertTrue(gost.table_mass("1.1", 30, 900) < formula < gost.table_mass("1.1", 30, 1000) * 1.02)

    def test_name_with_thread(self):
        self.assertEqual(gost.name("1.1", 30, 900, 250, "09Г2С"),
                         "Болт фундаментный (анкерный) тип 1.1 М-30х900, резьба 250 мм, 09Г2С ГОСТ 24379.1-2012")


@tagged("post_install", "-at_install")
class TestBoltCalc(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Calc = self.env["pmk.bolt.calc"]
        self.norm30 = self.env.ref("pmk_bolt.norm_m30")
        self.norm30.write({"round_09g2s_ton": 100000, "round_st3_ton": 80000, "sheet_ton": 50000,
                           "thread_rub": 100, "bend_rub": 50, "plate_rub": 200, "washer_rub": 20})
        self.env["pmk.price.policy"].search([]).write({"active": False})
        policy = self.env["pmk.price.policy"].create({
            "name": "Тест осень", "date_from": date(2026, 9, 1),
            "line_ids": [Command.create({"kind": "bolt", "markup_pct": 50})]})
        self.env["pmk.price.policy"].create({
            "name": "Тест зима", "date_from": date(2026, 12, 1),
            "line_ids": [Command.create({"kind": "bolt", "markup_pct": 30})]})
        self.policy = policy

    def _calc(self, day=date(2026, 10, 21), **line):
        vals = dict(bolt_type="2.1", diameter="30", length=600, steel="09Г2С", qty=10, nut_price=40)
        vals.update(line)
        return self.Calc.create({"date": day, "line_ids": [Command.create(vals)]})

    def test_cost_and_price(self):
        calc = self._calc()
        line = calc.line_ids
        self.assertTrue(calc.name.startswith("БЛТ-"))
        self.assertEqual(line.name, "Болт фундаментный (анкерный) тип 2.1 М-30х600, резьба 120 мм, 09Г2С ГОСТ 24379.1-2012")
        self.assertEqual(line.mass_one, 6.64)
        self.assertEqual(line.metal_ton, 100000)
        stud = gost.stud_kg("2.1", 30, 600)
        self.assertAlmostEqual(line.metal_rub, stud * 100, places=2)
        self.assertAlmostEqual(line.plate_rub, 2.08 * 50 + 200, places=2)
        self.assertAlmostEqual(line.washer_rub, 0.33 * 50 + 20, places=2)
        self.assertEqual(line.nuts_rub, 160, "2.1 — 4 гайки")
        self.assertEqual(line.thread_rub, 200, "2.1 — резьба с двух концов")
        self.assertEqual(line.work_rub, 0)
        self.assertEqual(line.markup_pct, 50)
        self.assertEqual(line.price_unit, float(int(line.cost_one * 1.5) + 1))
        self.assertIn("Гайка М30 ГОСТ 5915 × 4", line.kit_text)
        self.assertIn("Плита 120×120×20", line.kit_text)
        self.assertEqual(calc.total_qty, 10)
        self.assertAlmostEqual(calc.amount_total, line.price_unit * 10)

    def test_bent_bolt_extended_thread_and_season(self):
        calc = self._calc(day=date(2026, 12, 15), bolt_type="1.1", length=950, thread_len=250, steel="Ст3")
        line = calc.line_ids
        self.assertEqual(line.blank_mm, 950 + 90 - 60)
        self.assertEqual(line.markup_pct, 30, "зимняя политика")
        self.assertEqual(line.metal_ton, 80000, "Ст3")
        self.assertEqual(line.work_rub, 50, "один гиб")
        self.assertAlmostEqual(line.thread_rub, 100 * 250 / 120, places=2)
        self.assertIn("длина не из ряда ГОСТ", line.warning)
        self.assertIn("удлинённая резьба: +130 мм", line.warning)
        self.assertIn("резьба 250 мм", line.name)

    def test_nut_hint_and_manual_price(self):
        self._calc(nut_price=55, nut_kind="hardened")
        line = self._calc(nut_price=0, nut_kind="hardened").line_ids
        self.assertIn("55 ₽", line.nut_hint)
        self.assertIn("впишите цену гайки", line.warning)
        line.price_unit = 9999
        self.assertEqual(line.price_total, 9999 * 10)

    def test_wrong_diameter_for_type(self):
        line = self._calc(bolt_type="2.2", diameter="30").line_ids
        self.assertEqual(line.warning, "Тип 2.2 делают М56–М90")
        self.assertFalse(line.cost_one)

    def test_norm_checked_on_and_stale(self):
        norm = self.env.ref("pmk_bolt.norm_m24")
        norm.checked_on = False
        self.assertTrue(norm.stale)
        norm.thread_rub = 90
        self.assertEqual(norm.checked_on, date.today())
        self.assertEqual(norm.checked_by, self.env.user)
        self.assertFalse(norm.stale)

    def test_history_from_sale_lines(self):
        partner = self.env["res.partner"].create({"name": "ООО «Порт»"})
        product = self.env["product.product"].create({"name": "Позиция"})
        order = self.env["sale.order"].create({"partner_id": partner.id, "order_line": [Command.create({
            "product_id": product.id, "price_unit": 2599,
            "name": "Болт фундаментный (анкерный) тип 2.1 М-30х600 09Г2С ГОСТ 24379.1-2012"})]})
        self.assertTrue(order)
        line = self._calc().line_ids
        self.assertIn("2 599 ₽", line.history)
        other = self._calc(length=610).line_ids
        self.assertIn("не продавали", other.history)


@tagged("post_install", "-at_install")
class TestQuickAdd(TransactionCase):

    def test_parse_like_butik(self):
        from ..tools import parse
        vals, _notes, _error = parse.parse("бф 2.1 м30 640мм ст3 10шт")
        self.assertEqual(vals, {"bolt_type": "2.1", "diameter": "30", "length": 640, "steel": "Ст3", "qty": 10})
        vals, _n, _e = parse.parse("Болт фундаментный 2.1 М16х450 ГОСТ 24379.1-2012 09Г2С")
        self.assertEqual((vals["diameter"], vals["length"], vals["steel"]), ("16", 450, "09Г2С"))
        vals, _n, _e = parse.parse("2.1 м30*600 р250 09г2с 896шт калён гайка 120")
        self.assertEqual((vals["thread_len"], vals["qty"], vals["nut_kind"], vals["nut_price"]),
                         (250, 896, "hardened", 120.0))
        self.assertEqual(parse.parse("бф 2.1 м12 500")[2], "Тип 2.1 делают М16–М48")
        self.assertTrue(parse.parse("бф м30 600")[2].startswith("не указан тип"))

    def test_grid_like_butik(self):
        calc = self.env["pmk.bolt.calc"].create({})
        data = calc.bolt_save_row(False, {"name": "бф 2.1 м30 640мм ст3 10шт"})
        row = data["rows"][0]
        self.assertEqual(row["name"], "2.1 М30×640 · Ст3 · резьба 120")
        self.assertIn("ГОСТ 24379.1-2012", row["label"])
        self.assertIn("4 гайки М30", row["detail"])
        self.assertEqual(row["qty"], 10)
        # Ячейки: количество, гайки, цена гайки — как в Бутике.
        data = calc.bolt_save_row(row["id"], {"qty": "896", "nut_kind": "калёные", "nut_price": "45,5"})
        row = data["rows"][0]
        self.assertEqual((row["qty"], row["nut_kind"], row["nut_price"]), (896, "калёные", 45.5))
        # Правка записи без «шт» не сбрасывает количество.
        row = calc.bolt_save_row(row["id"], {"name": "2.1 М30×700 · Ст3 · резьба 120"})["rows"][0]
        self.assertEqual((row["name"], row["qty"]), ("2.1 М30×700 · Ст3 · резьба 120", 896))
        # Пустая строка (Enter в конце) — не болт и без пометок.
        data = calc.bolt_save_row(False, {"after_id": row["id"]})
        self.assertEqual((data["rows"][1]["name"], data["rows"][1]["warning"]), ("", ""))
        # Непонятая запись остаётся в ячейке с причиной.
        bad = calc.bolt_save_row(data["rows"][1]["id"], {"name": "бф м30 600"})["rows"][1]
        self.assertEqual((bad["name"], bad["bad"]), ("бф м30 600", True))
        self.assertTrue(bad["label"].startswith("не указан тип"))
        # Ctrl+V столбиком — в пустую строку и ниже.
        data = calc.bolt_insert_rows(bad["id"], [{"name": "1.1 м24х1000 09г2с 48шт"}, {"name": "бф 5 м36 800 ст3 20шт"}])
        self.assertEqual([r["name"] for r in data["rows"]],
                         ["2.1 М30×700 · Ст3 · резьба 120", "бф м30 600", "1.1 М24×1000 · 09Г2С · резьба 110",
                          "5 М36×800 · Ст3 · резьба 130"])
        data = calc.bolt_duplicate_row(data["rows"][0]["id"])
        self.assertEqual(len(data["rows"]), 5)
        data = calc.bolt_delete_row(data["rows"][1]["id"])
        self.assertEqual(len(data["rows"]), 4)
        self.assertEqual(data["count"], 896 + 48 + 20)
