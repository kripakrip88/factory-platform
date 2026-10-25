# -*- coding: utf-8 -*-
"""Опоры трубопроводов по ОСТ 36-146-88 (25.10.2026)."""
from odoo.tests import TransactionCase, tagged

from ..tools import catalog, parse
from ..tools import ost36_146 as ost


@tagged("post_install", "-at_install")
class TestOst(TransactionCase):

    def test_parts_mass_close_to_ost(self):
        """Детали дают 83–92 % «массы не более» ОСТ по всем строкам табл. 4 и 5 — геометрия
        корпуса (U + рёбра) и хомутов сходится; выпадающая строка — ошибка таблицы или модели."""
        for kind in ("kp", "kx"):
            for dn in ost.diameters(kind):
                for exe in ost.executions(kind, dn):
                    ratio = ost.mass(kind, dn, exe) / ost.ost_mass(kind, dn, exe)
                    self.assertTrue(0.82 < ratio < 0.93, "%s %s %s: %.3f" % (kind, dn, exe, ratio))

    def test_kx_219_a12_fixed(self):
        parts = {p["key"]: p for p in ost.parts("kx_fix", 219, "А12")}
        self.assertEqual(set(parts), {"corpus", "rib_end", "clamp", "bolt", "nut", "stop"})
        self.assertEqual(parts["clamp"]["qty"], 4)
        self.assertEqual(parts["bolt"]["name"], "Болт М20×60 ГОСТ 7798-70")
        self.assertEqual(parts["stop"]["qty"], 2)
        self.assertEqual(ost.name("kx_fix", 219, "А12", "09Г2С"),
                         "Опора неподвижная 219-КХ-А12-09Г2С ОСТ 36-146-88 (с упорами)")

    def test_one_hoop_for_short_small(self):
        """Табл. 19: КХ А11/А21 Дн 57–89 — один хомут (2 полухомута), иначе два."""
        self.assertEqual({p["key"]: p["qty"] for p in ost.parts("kx", 89, "А11")}["clamp"], 2)
        self.assertEqual({p["key"]: p["qty"] for p in ost.parts("kx", 108, "А11")}["clamp"], 4)

    def test_welded_corpus(self):
        keys = [p["key"] for p in ost.parts("kp", 219, "АС13")]
        self.assertEqual(keys[:2], ["bottom", "wall"])
        self.assertIn("rib", keys)
        self.assertIn("rib_end", keys)

    def test_checks(self):
        self.assertIn("только Дн 57–159", ost.check("kx_fix", 219, "А11"))
        self.assertEqual(ost.check("kx_fix", 108, "А11"), "")
        self.assertIn("Исполнения Б12", ost.check("kx", 219, "Б12"))
        self.assertIn("Дн 820", ost.check("kx", 820, "А12"))

    def test_own_height(self):
        """«Н=50» в счетах: корпус ниже на разницу с ОСТ — масса меньше."""
        self.assertLess(ost.mass("kx", 89, "А12", 50), ost.mass("kx", 89, "А12"))
        self.assertIn("Н=50 мм", ost.name("kx", 89, "А12", "Ст3пс", 50))


@tagged("post_install", "-at_install")
class TestParse(TransactionCase):

    def test_short_and_invoice_names(self):
        vals, _n, err = parse.parse("кх а12 219 09г2с 20шт")
        self.assertFalse(err)
        self.assertEqual((vals["opora_type"], vals["dn"], vals["execution"], vals["steel"], vals["qty"]),
                         ("kx", 219, "А12", "09Г2С", 20))
        vals, _n, err = parse.parse("Опора неподвижная 219-КХ-А22 Ду 219 (с упорами)  ОСТ 36-146-88")
        self.assertEqual((vals["opora_type"], vals["dn"], vals["execution"]), ("kx_fix", 219, "А22"))
        vals, _n, err = parse.parse("Опора корпусная хомутовая КХ Дн 630 мм А12 ОСТ 36-146-88 Н=100мм")
        self.assertEqual((vals["dn"], vals["height"]), (630, 0))
        vals, _n, err = parse.parse("Опора корпусная хомутовая КХ ДУ 89 А12  ОСТ 36-146-88 Н=50мм")
        self.assertEqual((vals["dn"], vals["height"]), (89, 50))
        vals, _n, err = parse.parse("кп ас13 530 ст3пс")
        self.assertEqual((vals["opora_type"], vals["execution"]), ("kp", "АС13"))
        self.assertTrue(parse.parse("гайка м20 2шт")[2])
        self.assertIn("по ОСТ нет", parse.parse("кх а13 159")[2])


@tagged("post_install", "-at_install")
class TestCalc(TransactionCase):

    def test_grid_line_parts_and_price(self):
        calc = self.env["pmk.opora.calc"].create({})
        data = calc.opora_rows()
        key = data["rows"][0]["id"]
        calc.opora_save_row(key, {"name": "кх неподв а12 219 09г2с 10шт"})
        line = calc.line_ids
        self.assertEqual(line.qty, 10)
        self.assertEqual(line.name, "Опора неподвижная 219-КХ-А12-09Г2С ОСТ 36-146-88 (с упорами)")
        self.assertEqual(len(line.part_ids), 6)
        self.assertAlmostEqual(line.mass_one, ost.mass("kx_fix", 219, "А12"), places=1)
        # Цена болтов вписана — стоимость строки состава по штукам; поправка не затирается пересчётом.
        bolt = line.part_ids.filtered(lambda p: p.auto_key == "bolt")
        calc.opora_save_row("p%s" % bolt.id, {"price": "25"})
        self.assertEqual(bolt.cost, 100)
        calc.opora_save_row(key, {"name": "кх неподв а12 219 09г2с 10шт"})
        self.assertEqual(bolt.price_unit, 25)
        self.assertTrue(bolt.edited)
        # Металл без цены в прайсе — пометка; цена листа вписана — стоимость по тоннам.
        corpus = line.part_ids.filtered(lambda p: p.auto_key == "corpus")
        calc.opora_save_row("p%s" % corpus.id, {"price": "100000"})
        self.assertAlmostEqual(corpus.cost, corpus.mass * 100, places=2)

    def test_bad_record_kept(self):
        calc = self.env["pmk.opora.calc"].create({})
        key = calc.opora_rows()["rows"][0]["id"]
        calc.opora_save_row(key, {"name": "кх а13 159"})
        self.assertIn("по ОСТ нет", calc.line_ids.parse_error)
        self.assertFalse(calc.line_ids.part_ids)

    def test_reference_filled(self):
        Ref = self.env["pmk.opora.ref"]
        self.assertTrue(Ref.search_count([("opora_type", "=", "kx"), ("dn", "=", 219), ("execution", "=", "А12")]))
        self.assertFalse(Ref.search_count([("opora_type", "=", "kx_fix"), ("dn", "=", 219), ("execution", "=", "А11")]))
        self.assertEqual(Ref.search_count([("opora_type", "=", "kp")]), len(ost.KP))
        # ОСТ 36-94-83: ОПП1 — с составом, остальные марки — справочник без состава.
        self.assertEqual(Ref.search_count([("opora_type", "=", "opp1")]), 20)
        opp2 = Ref.search([("designation", "=", "ОПП2-100.57")])
        self.assertTrue(opp2 and not opp2.has_parts and opp2.ost_mass == 1.24)


@tagged("post_install", "-at_install")
class TestOst3694(TransactionCase):
    """ОСТ 36-94-83 «Опоры подвижные» (25.10.2026): ОПП1 — состав по черт. 1, табл. 1."""

    def test_opp1_mass_within_ost(self):
        for dn in catalog.diameters("opp1"):
            for exe in ("100", "70"):
                ratio = catalog.mass("opp1", dn, exe) / catalog.ost_mass("opp1", dn, exe)
                self.assertTrue(0.85 < ratio <= 1.0, "ОПП1-%s.%s: %.3f" % (exe, dn, ratio))

    def test_opp1_parse_and_name(self):
        vals, _n, err = parse.parse("Опора корпусная ОПП1-100.18 ОСТ 36-94-83  Н=100мм")
        self.assertFalse(err)
        self.assertEqual((vals["opora_type"], vals["execution"], vals["dn"]), ("opp1", "100", 18.0))
        vals, _n, err = parse.parse("опп1 70 21,3 10шт 09г2с")
        self.assertEqual((vals["dn"], vals["qty"], vals["steel"]), (21.3, 10, "09Г2С"))
        self.assertIn("только в справочнике", parse.parse("ОПП2-100.57 ОСТ 36-94-83")[2])
        self.assertEqual(catalog.name("opp1", 21.3, "70", "Ст3пс"), "Опора подвижная ОПП1-70.21,3 ОСТ 36-94-83, Ст3пс")
        self.assertEqual(catalog.name("kx", 219.0, "А12", "09Г2С"), "Опора подвижная 219-КХ-А12-09Г2С ОСТ 36-146-88")

    def test_opp1_in_calc(self):
        calc = self.env["pmk.opora.calc"].create({})
        key = calc.opora_rows()["rows"][0]["id"]
        calc.opora_save_row(key, {"name": "опп1-100.18 6шт"})
        line = calc.line_ids
        self.assertEqual(line.qty, 6)
        self.assertEqual(set(line.part_ids.mapped("auto_key")), {"corpus", "rib"})
        self.assertAlmostEqual(line.mass_one, 0.565, delta=0.01)  # 0,439 + 0,126; поле — 2 знака
        self.assertEqual(line.ost_mass, 0.6)
