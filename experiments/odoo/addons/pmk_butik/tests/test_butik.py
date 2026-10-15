# -*- coding: utf-8 -*-
"""Бутик (15.10.2026): разбор наименования, распознавание по справочникам, вес,
вставка блока, привязка к сделке."""
from odoo.tests import TransactionCase, tagged

from ..tools import parse


@tagged("post_install", "-at_install")
class TestButik(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест бутика)"})
        cls.angle = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест бутика)", "gost": "ГОСТ",
            "size_label": "63x4", "mass_per_meter": 3.9})
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест бутика)", "thickness_mm": 10.0, "gost": "ГОСТ",
            "mass_per_sqm": 78.5})

    def test_parse(self):
        self.assertEqual(parse.classify("Лист 10х60")["kind"], "sheet")
        self.assertEqual(parse.classify("Лист 10х60")["width"], 60.0)
        info = parse.classify("Пластина 3100х85х0,7")
        self.assertEqual((info["thickness"], info["width"], info["length"]), (0.7, 85.0, 3100.0))
        self.assertEqual(parse.classify("Болт М10х40")["kind"], "piece")
        self.assertEqual(parse.classify("Уголок 63х4")["kind"], "linear")
        # справочник метизов пишет «Болт М10×40»: русская М и знак умножения
        self.assertEqual(parse.piece_query("болт M10x40"), "болт М10×40")
        self.assertEqual(parse.piece_query("Анкер М10 х 100"), "Анкер М10×100")

    def test_decode_short_line(self):
        """Короткая запись, как в зонтах (Антон, 16.10)."""
        dec = parse.decode("д1 шв10 1200мм 10шт 09г")
        self.assertEqual((dec["pos"], dec["name"], dec["length_mm"], dec["qty"], dec["grade"]),
                         ("Д1", "Швеллер 10", 1200.0, 10.0, "09Г2С"))
        dec = parse.decode("пл2 200х140х20мм ст3 10шт")
        self.assertEqual((dec["pos"], dec["name"], dec["width"], dec["length_mm"], dec["qty"], dec["grade"]),
                         ("Пл2", "Пластина 20", 140.0, 200.0, 10.0, "Ст3"))
        dec = parse.decode("болт 10х110 8.8")
        self.assertEqual((dec["name"], dec["grade"]), ("Болт М10×110", "кл. 8.8"))
        dec = parse.decode("гф21 60мкм")
        self.assertEqual((dec["name"], dec["kind"]), ("Грунт ГФ-021, 60 мкм", "coating"))
        self.assertEqual(parse.decode("шв10п 600 мм 2 шт")["name"], "Швеллер 10П")
        self.assertEqual(parse.decode("уг 63 4")["name"], "Уголок 63х4")
        # обычная запись Бутова не переписывается
        for plain in ("Уголок 63х4", "Лист 10х60", "Болт М10х40"):
            self.assertIsNone(parse.decode_for_cell(plain), plain)

    def test_short_line_fills_columns(self):
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        detail = spec.butik_rows()["rows"][1]
        row = spec.butik_save_row(detail["id"], {"name": "пл2 200х140х20мм ст3 10шт"})["rows"][1]
        self.assertEqual((row["pos"], row["name"], row["width"], row["length_mm"], row["qty"], row["grade"]),
                         ("Пл2", "Пластина 20", 140.0, 200.0, 10.0, "Ст3"))
        self.assertTrue(row["is_sheet"])
        rows = spec.butik_insert_rows(detail["id"], [{"name": "гф21 60мкм"}])["rows"]
        self.assertEqual(rows[2]["match_state"], "coating")
        # вставка в пустую строку занимает её место
        spec2 = self.env["pmk.butik.spec"].create({"subject": "Тест 2"})
        empty = spec2.butik_rows()["rows"][1]
        rows = spec2.butik_insert_rows(empty["id"], [{"name": "д1 шв10 1200мм 10шт"}])["rows"]
        self.assertEqual([r["name"] for r in rows], ["Изделие 1", "Швеллер 10"])

    def test_fastener_typed_like_excel(self):
        bolt = self.env["pmk.metal.fastener"].create({
            "name": "Болт М10×40 (тест бутика)", "weight_kg": 0.0281})
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        detail = spec.butik_rows()["rows"][1]
        spec.butik_save_row(detail["id"], {"name": "Болт М10х40", "qty": "4"})
        line = spec.line_ids.filtered(lambda l: l.id == detail["id"])
        # справочник может уже знать этот болт — проверяем размер, а не запись
        self.assertIn("М10×40", line.fastener_id.name)
        self.assertAlmostEqual(line.weight_total, 4 * line.fastener_id.weight_kg, places=3)
        self.assertTrue(bolt)

    def test_rows_weight_and_paste(self):
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        data = spec.butik_rows()
        self.assertEqual(data["products"], 1)
        product, detail = data["rows"]
        spec.butik_save_row(product["id"], {"product_qty": "10"})
        spec.butik_save_row(detail["id"], {"name": "Уголок 63х4", "length_mm": "1000", "qty": "2"})
        line = spec.line_ids.filtered(lambda l: l.id == detail["id"])
        self.assertEqual(line.profile_id, self.angle, "умный поиск справочника")
        self.assertAlmostEqual(line.weight_one, 3.9, places=2)
        self.assertAlmostEqual(line.qty_total, 20.0)
        self.assertAlmostEqual(line.weight_total, 78.0, places=1)
        data = spec.butik_insert_rows(detail["id"], [
            {"pos": "2", "name": "Лист 10х60", "length_mm": "180", "qty": "6", "grade": "Ст3сп"}])
        sheet_row = data["rows"][2]
        self.assertEqual(sheet_row["name"], "Лист 10х60")
        sheet_line = spec.line_ids.filtered(lambda l: l.id == sheet_row["id"])
        # в базе может быть свой лист 10 мм — проверяем толщину, а не запись
        self.assertEqual(sheet_line.sheet_id.thickness_mm, 10.0)
        self.assertAlmostEqual(sheet_line.weight_one, sheet_line.sheet_id.mass_per_sqm * 60 * 180 / 1e6, places=3)
        self.assertTrue(spec.butik_suggest("уг 63 4"))

    def test_sheet_two_sizes(self):
        """Лист — ширина своей колонкой: из «Лист 10х60» сама, или руками;
        выбор листа из подсказки ширину не теряет."""
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        detail = spec.butik_rows()["rows"][1]
        rows = spec.butik_save_row(detail["id"], {"name": "Лист 10", "length_mm": "180", "qty": "1"})["rows"]
        self.assertTrue(rows[1]["is_sheet"])
        self.assertEqual(rows[1]["width"], 0.0)
        rows = spec.butik_save_row(detail["id"], {"width": "60"})["rows"]
        self.assertEqual(rows[1]["width"], 60.0)
        line = spec.line_ids.filtered(lambda l: l.id == detail["id"])
        self.assertAlmostEqual(rows[1]["weight_one"], line.sheet_id.mass_per_sqm * 60 * 180 / 1e6, places=3)
        # три числа в наименовании — ширина и длина в колонки
        rows = spec.butik_save_row(detail["id"], {"name": "Пластина 3100х85х0,7", "length_mm": ""})["rows"]
        self.assertEqual((rows[1]["width"], rows[1]["length_mm"]), (85.0, 3100.0))
        # лист из подсказки: ширина остаётся
        spec.butik_set_position(detail["id"], "sheet:%d" % self.sheet.id)
        self.assertEqual(spec.butik_rows()["rows"][1]["width"], 85.0)

    def test_link_deal(self):
        lead = self.env["crm.lead"].create({"name": "Сделка бутика", "type": "opportunity"})
        spec = self.env["pmk.butik.spec"].create({"lead_id": lead.id})
        self.assertEqual(spec.lead_id, lead)
        self.assertTrue(spec.name.startswith("БТ-"))
