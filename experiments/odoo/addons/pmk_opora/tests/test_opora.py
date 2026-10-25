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


@tagged("post_install", "-at_install")
class TestMarkup(TransactionCase):
    """Наценку ставит менеджер (Антон 25.10.2026): без неё цены нет."""

    def test_no_markup_no_price(self):
        calc = self.env["pmk.opora.calc"].create({})
        key = calc.opora_rows()["rows"][0]["id"]
        calc.opora_save_row(key, {"name": "кх а12 219 10шт"})
        line = calc.line_ids
        line.part_ids.filtered(lambda p: p.auto_key == "corpus").price_ton = 100000
        line.markup_pct = 0
        self.assertEqual(line.price_unit, 0)
        self.assertIn("впишите наценку", line.warning)
        calc.opora_save_row(key, {"markup": "150"})
        self.assertGreater(line.price_unit, line.cost_one * 2.4)
        self.assertNotIn("впишите наценку", line.warning)


@tagged("post_install", "-at_install")
class TestOporaToSpec(TransactionCase):
    """Опора → расчёт изделием «Конструкций» (Антон 25.10.2026, вариант 1): лист — номенклатурой."""

    def test_kx57_to_konstr(self):
        partner = self.env["res.partner"].create({"name": "Заказчик опор (тест)", "is_company": True})
        calc = self.env["pmk.opora.calc"].create({"partner_id": partner.id})
        key = calc.opora_rows()["rows"][0]["id"]
        calc.opora_save_row(key, {"name": "кх а12 57 10шт"})
        line = calc.line_ids
        bolt = line.part_ids.filtered(lambda p: p.auto_key == "bolt")
        calc.opora_save_row("p%s" % bolt.id, {"price": "12"})
        line.markup_pct = 60
        action = calc.action_opora_to_spec()
        spec = self.env["pmk.metal.spec"].browse(action["res_id"])
        self.assertEqual((calc.spec_id, spec.partner_id, spec.cat_metal), (spec, partner, True))
        product = line.konstr_product_id
        self.assertEqual((product.name, product.qty), (line.name, 10))
        sheets = product.line_ids.filtered(lambda l: l.calc_mode == "sheet")
        corpus = sheets.filtered(lambda l: l.detail_name.startswith("Корпус"))
        self.assertEqual((corpus.sheet_id.thickness_mm, corpus.a_mm, corpus.b_mm, corpus.qty), (3.0, 257.0, 340.0, 1))
        self.assertEqual(corpus.sheet_id.sheet_type, "Гладкий")
        self.assertTrue(corpus.grade_id or corpus.pmk_grade_text)
        rib = sheets.filtered(lambda l: l.detail_name.startswith("Ребро торцевое"))
        self.assertEqual((rib.a_mm, rib.b_mm, rib.qty), (44.0, 107.0, 2))
        clamp = sheets.filtered(lambda l: l.detail_name.startswith("Полухомут"))
        self.assertEqual((clamp.sheet_id.thickness_mm, clamp.qty), (6.0, 4))
        fasteners = product.line_ids.filtered(lambda l: l.calc_mode == "fastener")
        bolt_line = fasteners.filtered(lambda l: l.fastener_id.fastener_type == "bolt")
        self.assertEqual((bolt_line.fastener_id.size_label, bolt_line.qty, bolt_line.price_state), ("М12×40", 4, "manual"))
        self.assertAlmostEqual(bolt_line.price_unit, 12)
        nut_line = fasteners.filtered(lambda l: l.fastener_id.fastener_type == "nut")
        self.assertEqual(nut_line.fastener_id.size_label, "М12")
        # Второй перенос — то же изделие.
        calc.action_opora_to_spec()
        self.assertEqual(line.konstr_product_id, product)
        self.assertEqual(len(spec.product_ids), 1)
