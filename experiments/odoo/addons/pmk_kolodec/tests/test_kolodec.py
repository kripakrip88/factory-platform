# -*- coding: utf-8 -*-
"""Металлоизделия колодцев по ТПР 901-09-11.84 и 902-09-22.84 (25.10.2026)."""
from odoo.tests import TransactionCase, tagged

from ..tools import alb901_5, alb902_7, catalog, parse


@tagged("post_install", "-at_install")
class TestAlbums(TransactionCase):

    def test_st902_matches_album(self):
        """Альбом VII: A = 300·n, масса по деталям — 98–100 % таблицы (таблица и спецификация согласны)."""
        for mark in catalog.marks("st902"):
            a, n, album = alb902_7.ST[mark[3:]]
            self.assertEqual(a, 300 * n)
            self.assertEqual(alb902_7.ST_TOP + (n - 1) * alb902_7.ST_STEP + alb902_7.ST_BOTTOM, a)
            if album:
                self.assertTrue(0.97 < catalog.mass("st902", mark) / album <= 1.005, mark)

    def test_st901_one_rung_less_than_album(self):
        """Альбом V: в спецификации на ступень больше, чем помещается в A (кроме С-4) — берём чертёж."""
        for mark in catalog.marks("st901"):
            diff = alb901_5.ST[mark][5] - catalog.mass("st901", mark)
            expected = 0 if mark == "С-4" else 0.96
            self.assertAlmostEqual(diff, expected, delta=0.12, msg=mark)  # масса уголка в альбоме округлена

    def test_ms_and_zo_match_album(self):
        for mark in catalog.marks("ms"):
            self.assertAlmostEqual(catalog.mass("ms", mark), catalog.album_mass("ms", mark), delta=0.02)
        self.assertAlmostEqual(catalog.mass("zo", "ЗО"), 15.8, delta=0.1)

    def test_pr_sketch_close_to_album(self):
        for mark in catalog.marks("pr"):
            ratio = catalog.mass("pr", mark) / catalog.album_mass("pr", mark)
            self.assertTrue(0.9 < ratio < 1.15, "%s: %.2f" % (mark, ratio))

    def test_names(self):
        self.assertEqual(catalog.name("st902", "С1-04"), "Стремянка колодца С1-04 (длина лестницы 1,8 м) ТПР 902-09-22.84")
        self.assertEqual(catalog.name("st901", "С-4"), "Стремянка колодца С-4 (длина лестницы 2,25 м) ТПР 901-09-11.84")
        self.assertIn("МС-5 (B=90 мм)", catalog.name("ms", "МС-5"))


@tagged("post_install", "-at_install")
class TestParse(TransactionCase):

    def _p(self, text):
        vals, _n, err = parse.parse(text)
        self.assertFalse(err, text)
        return vals["item_type"], vals["mark"]

    def test_invoice_names(self):
        self.assertEqual(self._p("Стремянка водопроводного колодца С-1-04 (длина лестницы 1,8 м) ТПР 902-09-22.84"),
                         ("st902", "С1-04"))
        self.assertEqual(self._p("Стремянка С1 ТПР 902-09-22.84"), ("st902", "С1-00"))
        self.assertEqual(self._p("Стремянка С1.08 ТПР 902-09-22.84"), ("st902", "С1-08"))
        self.assertEqual(self._p("Стремянка водопроводного колодца С-4 (длина лестницы 2,25 м) ТПР 901-09-11.84"),
                         ("st901", "С-4"))
        self.assertEqual(self._p("Соединительный элемент колодец МС-5 (ширина90) ТПР 901-09-11.84"), ("ms", "МС-5"))
        self.assertEqual(self._p("Элемент соединительный МС-3 по инд.чертежу РД 902-09-22.84 (УКУХ-001010)"), ("ms902", "МС-3"))
        self.assertEqual(self._p("мс-5 100шт"), ("ms902", "МС-5"))
        self.assertEqual(self._p("Скоба ходовая МН-1"), ("mn1", "МН1"))
        self.assertEqual(self._p("Стремянка водопроводного колодца С-1-16 (длина лестницы 5,4 м) ТПР 902-09-22.84"),
                         ("st902", "С1-16"))

    def test_short(self):
        vals, _n, err = parse.parse("с1-04 10шт 09г2с")
        self.assertEqual((vals["mark"], vals["qty"], vals["steel"]), ("С1-04", 10, "09Г2С"))
        self.assertEqual(self._p("с-5 901"), ("st901", "С-5"))
        self.assertEqual(self._p("стремянка 1,8 м"), ("st902", "С1-04"))
        self.assertEqual(self._p("стремянка 2250"), ("st901", "С-4"))
        self.assertEqual(self._p("проставка ду300"), ("pr", "Ду300"))
        self.assertEqual(self._p("1219.01.000-05"), ("pr", "Ду600"))
        self.assertEqual(self._p("зо 3шт"), ("zo", "ЗО"))
        self.assertEqual(self._p("крышка к1"), ("k1", "К1"))

    def test_rejects(self):
        self.assertIn("НТС", parse.parse("Лестница стремянка h=3,0м НТС 62-91-111А")[2])
        self.assertIn("нет", parse.parse("с1-19")[2])
        self.assertTrue(parse.parse("болт м16х190 8шт")[2])


@tagged("post_install", "-at_install")
class TestCalc(TransactionCase):

    def test_grid_line_parts_and_price(self):
        calc = self.env["pmk.kolodec.calc"].create({})
        key = calc.kolodec_rows()["rows"][0]["id"]
        calc.kolodec_save_row(key, {"name": "с1-04 10шт"})
        line = calc.line_ids
        self.assertEqual(line.qty, 10)
        self.assertEqual(line.name, "Стремянка колодца С1-04 (длина лестницы 1,8 м) ТПР 902-09-22.84")
        self.assertEqual(set(line.part_ids.mapped("auto_key")), {"angle", "rung"})
        self.assertAlmostEqual(line.mass_one, catalog.mass("st902", "С1-04"), places=1)
        self.assertEqual(line.album_mass, 19.5)
        # Цена уголка вписана руками — стоимость по тоннам, пересчёт не затирает.
        angle = line.part_ids.filtered(lambda p: p.auto_key == "angle")
        calc.kolodec_save_row("p%s" % angle.id, {"price": "100000"})
        self.assertAlmostEqual(angle.cost, angle.mass * 100, places=2)
        calc.kolodec_save_row(key, {"name": "с1-04 10шт"})
        self.assertEqual(angle.price_ton, 100000)
        self.assertTrue(angle.edited)

    def test_pr_buy_parts(self):
        calc = self.env["pmk.kolodec.calc"].create({})
        key = calc.kolodec_rows()["rows"][0]["id"]
        calc.kolodec_save_row(key, {"name": "проставка ду100 2шт"})
        line = calc.line_ids
        stud = line.part_ids.filtered(lambda p: p.auto_key == "stud")
        self.assertFalse(stud.metal)
        self.assertEqual(stud.qty, 8)
        calc.kolodec_save_row("p%s" % stud.id, {"price": "45"})
        self.assertEqual(stud.cost, 360)
        self.assertIn("эскиз", line.warning)

    def test_bad_record_kept(self):
        calc = self.env["pmk.kolodec.calc"].create({})
        key = calc.kolodec_rows()["rows"][0]["id"]
        calc.kolodec_save_row(key, {"name": "мс-9"})
        self.assertTrue(calc.line_ids.parse_error)
        self.assertFalse(calc.line_ids.part_ids)

    def test_reference_filled(self):
        Ref = self.env["pmk.kolodec.ref"]
        self.assertEqual(Ref.search_count([("item_type", "=", "st902")]), 19)
        self.assertEqual(Ref.search_count([("item_type", "=", "st902"), ("outside", "=", True)]), 6)
        self.assertEqual(Ref.search_count([("item_type", "=", "ms")]), 8)
        self.assertEqual(Ref.search_count([("item_type", "=", "ms902")]), 8)
        self.assertEqual(Ref.search([("mark", "=", "С-1")]).rungs, 4)
