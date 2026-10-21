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
        self.env.ref("pmk_bolt.norm_m30").write({
            "round_09g2s_ton": 100000, "round_st3_ton": 80000, "sheet_ton": 50000})
        self.env["pmk.price.policy"].search([]).write({"active": False})
        self.env["pmk.price.policy"].create({
            "name": "Тест осень", "date_from": date(2026, 9, 1),
            "line_ids": [Command.create({"kind": "bolt", "markup_pct": 50})]})
        self.env["pmk.price.policy"].create({
            "name": "Тест зима", "date_from": date(2026, 12, 1),
            "line_ids": [Command.create({"kind": "bolt", "markup_pct": 30})]})

    def _calc(self, day=date(2026, 10, 21), nut=40, **line):
        vals = dict(bolt_type="2.1", diameter="30", length=600, steel="09Г2С", qty=10)
        vals.update(line)
        calc = self.Calc.create({"date": day, "line_ids": [Command.create(vals)]})
        nuts = calc.line_ids.part_ids.filtered(lambda p: p.auto_key == "nut")
        nuts._pmk_user_write({"price_unit": nut})
        return calc

    def _part(self, line, key):
        return line.part_ids.filtered(lambda p: p.auto_key == key)

    def test_composition_from_gost(self):
        calc = self._calc()
        line = calc.line_ids
        self.assertTrue(calc.name.startswith("БЛТ-"))
        self.assertEqual(line.name, "Болт фундаментный (анкерный) тип 2.1 М-30х600, резьба 120 мм, 09Г2С ГОСТ 24379.1-2012")
        self.assertEqual(line.part_ids.mapped("auto_key"), ["stud", "nut", "washer", "plate"],
                         "только материалы — работу не считаем")
        stud = self._part(line, "stud")
        self.assertEqual(stud.price_ton, 100000)
        self.assertAlmostEqual(stud.cost, round(gost.stud_kg("2.1", 30, 600), 3) * 100, places=2)
        self.assertEqual(self._part(line, "nut").qty, 4, "2.1 — 4 гайки")
        self.assertEqual(self._part(line, "nut").cost, 160)
        self.assertAlmostEqual(self._part(line, "plate").price_unit, round(2.08 * 50, 2))
        self.assertAlmostEqual(self._part(line, "washer").price_unit, round(0.33 * 50, 2))
        self.assertAlmostEqual(line.cost_one, sum(line.part_ids.mapped("cost")), places=2)
        self.assertEqual(line.markup_pct, 50)
        self.assertEqual(line.price_unit, float(int(line.cost_one * 1.5) + 1))
        self.assertEqual(line.mass_one, 6.64)
        self.assertEqual(calc.total_qty, 10)

    def test_extra_nuts_kept_on_recalc(self):
        """Антон: «иногда просят дополнительные гайки … скорректировать при расчёте»."""
        line = self._calc().line_ids
        nut = self._part(line, "nut")
        nut._pmk_user_write({"qty": 6})
        self.assertTrue(nut.edited)
        self.assertAlmostEqual(line.mass_one, 6.64 + 2 * gost.NUT_KG[30], places=3)
        line.length = 700  # пересчёт болта
        self.assertEqual((nut.qty, nut.price_unit), (6, 40), "поправленное не затёрто")
        self.assertIn("заготовка 700 мм", self._part(line, "stud").name)
        line.bolt_type = "1.1"  # у 1.1 плиты нет
        self.assertFalse(self._part(line, "plate"))

    def test_bent_bolt_extended_thread_and_season(self):
        line = self._calc(day=date(2026, 12, 15), bolt_type="1.1", length=950, thread_len=250, steel="Ст3").line_ids
        self.assertEqual(line.blank_mm, 950 + 90 - 60)
        self.assertEqual(line.markup_pct, 30, "зимняя политика")
        self.assertEqual(self._part(line, "stud").price_ton, 80000, "Ст3")
        self.assertIn("длина не из ряда ГОСТ", line.warning)
        self.assertIn("удлинённая резьба: +130 мм", line.warning)

    def test_nut_hint_and_warning(self):
        self._calc(nut=55, nut_kind="hardened")
        line = self._calc(nut=0, nut_kind="hardened").line_ids
        self.assertIn("55 ₽", line._pmk_nut_hint())
        self.assertIn("впишите цену гайки", line.warning)
        line.price_unit = 9999
        self.assertEqual(line.price_total, 9999 * 10)

    def test_wrong_diameter_for_type(self):
        line = self._calc(bolt_type="2.2", diameter="30").line_ids
        self.assertEqual(line.warning, "Тип 2.2 делают М56–М90")
        self.assertFalse(line.cost_one)
        self.assertFalse(line.part_ids)

    def test_norm_checked_on_and_stale(self):
        norm = self.env.ref("pmk_bolt.norm_m24")
        norm.checked_on = False
        self.assertTrue(norm.stale)
        norm.sheet_ton = 70000
        self.assertEqual(norm.checked_on, date.today())
        self.assertEqual(norm.checked_by, self.env.user)
        self.assertFalse(norm.stale)

    def test_history_from_sale_lines(self):
        partner = self.env["res.partner"].create({"name": "ООО «Порт»"})
        product = self.env["product.product"].create({"name": "Позиция"})
        self.env["sale.order"].create({"partner_id": partner.id, "order_line": [Command.create({
            "product_id": product.id, "price_unit": 2599,
            "name": "Болт фундаментный (анкерный) тип 2.1 М-30х600 09Г2С ГОСТ 24379.1-2012"})]})
        self.assertIn("2 599 ₽", self._calc().line_ids.history)
        self.assertIn("не продавали", self._calc(length=610).line_ids.history)


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

    def test_grid_bolts_and_composition(self):
        calc = self.env["pmk.bolt.calc"].create({})
        rows = calc.bolt_rows()["rows"]
        self.assertEqual((len(rows), rows[0]["kind"], rows[0]["name"]), (1, "product", ""), "пустая строка болта")
        bolt_key = rows[0]["id"]
        rows = calc.bolt_save_row(bolt_key, {"name": "бф 2.1 м30 640мм ст3 10шт калён гайка 45"})["rows"]
        self.assertEqual(rows[0]["name"], "2.1 М30×640 · Ст3 · резьба 120")
        self.assertEqual(rows[0]["product_qty"], 10)
        self.assertEqual([r["kind"] for r in rows], ["product"] + ["detail"] * 4, "болт + состав по ГОСТ")
        nut = next(r for r in rows if r["name"].startswith("Гайка"))
        self.assertEqual((nut["qty"], nut["qty_total"], nut["price"]), (4, 40, 45), "цена гайки из записи")
        # Доп. гайки — правкой количества в строке состава.
        rows = calc.bolt_save_row(nut["id"], {"qty": "6"})["rows"]
        nut = next(r for r in rows if r["name"].startswith("Гайка"))
        self.assertEqual((nut["qty"], nut["changed"]), (6, "6 вместо 4 по ГОСТ"))
        # Enter внизу → пустая строка состава; своя строка — в состав, запись болта — новый болт.
        rows = calc.bolt_save_row(False, {"after_id": rows[-1]["id"]})["rows"]
        own = rows[-1]
        self.assertEqual((own["kind"], own["parent"]), ("detail", bolt_key))
        rows = calc.bolt_save_row(own["id"], {"name": "шайба м30 доп 2шт 15"})["rows"]
        own = rows[-1]
        self.assertEqual((own["qty"], own["price"], own["cost"]), (2, 15, 30))
        rows = calc.bolt_save_row(False, {"after_id": own["id"]})["rows"]
        rows = calc.bolt_save_row(rows[-1]["id"], {"name": "бф 1.1 м24х1000 09г2с 48шт"})["rows"]
        products = [r for r in rows if r["kind"] == "product"]
        self.assertEqual([p["name"] for p in products],
                         ["2.1 М30×640 · Ст3 · резьба 120", "1.1 М24×1000 · 09Г2С · резьба 110"])
        # Ctrl+V столбиком: болт и строка состава.
        data = calc.bolt_insert_rows(products[1]["id"], [{"name": "бф 5 м36 800 ст3 20шт"}, {"name": "гайка м36 1шт 70"}])
        products = [r for r in data["rows"] if r["kind"] == "product"]
        self.assertEqual(len(products), 3)
        self.assertTrue(any(r["name"] == "гайка м36 1шт 70" and r["parent"] == products[2]["id"] for r in data["rows"]))
        # Копия болта — с составом и правками; удаление.
        data = calc.bolt_duplicate_row(products[0]["id"])
        self.assertEqual(len([r for r in data["rows"] if r["kind"] == "product"]), 4)
        copy_nut = [r for r in data["rows"] if r["name"].startswith("Гайка М30")]
        self.assertEqual([r["qty"] for r in copy_nut], [6, 6])
        data = calc.bolt_delete_row(products[0]["id"])
        self.assertEqual(len([r for r in data["rows"] if r["kind"] == "product"]), 3)
        # Непонятая запись болта — в ячейке с причиной.
        bad_key = data["rows"][0]["id"]
        bad = calc.bolt_save_row(bad_key, {"name": "бф м30 600"})["rows"][0]
        self.assertEqual((bad["name"], bad["bad"]), ("бф м30 600", True))
