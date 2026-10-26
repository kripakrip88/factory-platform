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

    def test_sheet_line(self):
        """Лист строкой (Антон 16.10): «т1 10мм 100х100мм 10шт», номер не всегда."""
        dec = parse.decode_for_cell("т1 10мм 100х100мм 10шт")
        self.assertEqual((dec["pos"], dec["name"], dec["width"], dec["length_mm"], dec["qty"]),
                         ("Т1", "Лист 10", 100.0, 100.0, 10.0))
        dec = parse.decode_for_cell("4 мм 250х1200 6 шт с255")
        self.assertEqual((dec["name"], dec["width"], dec["length_mm"], dec["qty"], dec["grade"]),
                         ("Лист 4", 250.0, 1200.0, 6.0, "С255"))
        self.assertNotIn("pos", dec)
        # номер без цифры — тоже номер (на боевом «тт» терялся, 16.10)
        dec = parse.decode_for_cell("тт 10мм 100х100мм 10шт")
        self.assertEqual((dec["pos"], dec["name"], dec["qty"]), ("Тт", "Лист 10", 10.0))
        self.assertEqual(parse.decode_for_cell("кр3 шв10 600мм 2шт")["pos"], "Кр3")
        self.assertEqual(parse.decode_for_cell("а шв10 600мм 2шт")["pos"], "А")
        dec = parse.decode_for_cell("пл2 шв10 600мм")
        self.assertEqual((dec["pos"], dec["name"]), ("Пл2", "Швеллер 10"), "номер «пл2» — не лист")
        self.assertEqual(parse.decode_for_cell("кр20 1000мм 2шт")["name"], "Круг 20")
        # прокат с длиной в мм — по-прежнему длина
        self.assertEqual(parse.decode_for_cell("уг63х4 1500мм 4шт")["length_mm"], 1500.0)
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        detail = spec.butik_rows()["rows"][1]
        row = spec.butik_save_row(detail["id"], {"name": "т1 10мм 100х100мм 10шт"})["rows"][1]
        self.assertEqual((row["pos"], row["width"], row["length_mm"], row["qty"]), ("Т1", 100.0, 100.0, 10.0))
        self.assertTrue(row["is_sheet"])
        self.assertGreater(row["weight_one"], 0)

    def test_checker_sheet(self):
        """«риф 5мм» — рифлёный лист, не гладкий (Антон 20.10.2026); одно «Nмм» у
        листа — толщина, не длина."""
        dec = parse.decode_for_cell("риф 5мм 200х300мм 2шт")
        self.assertEqual((dec["name"], dec["width"], dec["length_mm"], dec["qty"]),
                         ("Лист рифлёный 5", 200.0, 300.0, 2.0))
        self.assertEqual(parse.decode_for_cell("пл 10мм")["name"], "Пластина 10")
        self.assertNotIn("length_mm", parse.decode_for_cell("пл 10мм"))
        self.assertEqual(parse.sheet_query("Лист рифлёный 5", 5), "риф 5")
        self.assertEqual(parse.sheet_query("Лист ПВЛ 5", 5), "пвл 5")
        self.assertEqual(parse.sheet_query("Лист 10", 10), "лист 10")
        checker = self.env["pmk.metal.sheet"].create({
            "sheet_type": "Рифлёный", "thickness_mm": 5.0, "gost": "ГОСТ 8568-77", "mass_per_sqm": 41.8})
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест рифлёного"})
        detail = spec.butik_rows()["rows"][1]
        spec.butik_save_row(detail["id"], {"name": "риф 5мм 200х300мм 2шт"})
        line = spec.line_ids.filtered(lambda l: l.kind == "detail")[:1]
        self.assertIn("Рифл", line.sheet_id.sheet_type or "", line.sheet_id.display_name)
        self.assertAlmostEqual(line.sheet_id.mass_per_sqm, checker.mass_per_sqm)

    def test_short_line_fills_columns(self):
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        detail = spec.butik_rows()["rows"][1]
        row = spec.butik_save_row(detail["id"], {"name": "пл2 200х140х20мм ст3 10шт"})["rows"][1]
        self.assertEqual((row["pos"], row["name"], row["width"], row["length_mm"], row["qty"], row["grade"]),
                         ("Пл2", "Пластина 20", 140.0, 200.0, 10.0, "Ст3"))
        self.assertTrue(row["is_sheet"])
        rows = spec.butik_insert_rows(detail["id"], [{"name": "гф21 60мкм"}])["rows"]
        self.assertEqual(rows[2]["match_state"], "coating")
        # покрытие — из справочника, расход пересчитан на 60 мкм
        coat = self.env["pmk.paint.coating"].create({
            "name": "Грунт ГФ-021 (тест бутика)", "paint_type": "primer", "consumption": 0.1,
            "base_thickness_um": 20.0})
        line = spec.line_ids.filtered(lambda l: l.id == rows[2]["id"])
        spec.butik_set_position(line.id, "coating:%d" % coat.id)
        self.assertEqual(line.coating_um, 60.0)
        self.assertIn("→ 0,3 кг/м² при 60 мкм", line._butik_label())
        self.assertEqual(parse.coating_query("Горячее цинкование"), "Цинкование")
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
        spec.butik_save_row(detail["id"], {"name": "Болт М10х40", "grade": "кл. 8.8", "qty": "4"})
        line = spec.line_ids.filtered(lambda l: l.id == detail["id"])
        # 26.10.2026: класс — в «Марке», позиция своего класса (цены 5.8 / 8.8 / 10.9 разные)
        self.assertEqual(line.fastener_id, self.env.ref("pmk_calc.fast2_bolt_10_40_88_black"))
        self.assertAlmostEqual(line.weight_total, 4 * line.fastener_id.weight_kg, places=3)
        self.assertTrue(bolt)
        # Класс не указан, а классов несколько — не угадываем: «не найдено», уточнить класс.
        spec.butik_save_row(detail["id"], {"grade": "кл. 5.8"})
        self.assertEqual(line.fastener_id, self.env.ref("pmk_calc.fast2_bolt_10_40_58_black"), "сменили класс")
        spec.butik_save_row(detail["id"], {"grade": ""})
        self.assertFalse(line.fastener_id)

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

    def test_product_row_weight(self):
        """Строка изделия несёт вес своих деталей: на одно изделие и всего."""
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        product, detail = spec.butik_rows()["rows"]
        spec.butik_save_row(product["id"], {"product_qty": "3"})
        rows = spec.butik_save_row(detail["id"], {"name": "Уголок 63х4", "length_mm": "1000", "qty": "2"})["rows"]
        head = rows[0]
        self.assertEqual(rows[1]["parent"], head["id"])
        self.assertAlmostEqual(head["weight_total"], rows[1]["weight_total"], places=3)
        self.assertAlmostEqual(head["weight_one"], rows[1]["weight_total"] / 3, places=3)
        data = spec.butik_rows()
        self.assertAlmostEqual(data["weight_kg"], rows[1]["weight_total"], places=1, msg="без двойного счёта")
        self.assertAlmostEqual(spec.weight_t, spec.weight_kg / 1000, places=3)

    def test_flow_graph(self):
        """«Связи»: расчёт «Бутик» на схеме своей сделки."""
        lead = self.env["crm.lead"].create({"name": "Сделка бутика (связи)", "type": "opportunity"})
        spec = self.env["pmk.butik.spec"].create({"lead_id": lead.id})
        graph = self.env["pmk.flow.builder"].get_flow_graph("pmk.butik.spec", spec.id)
        ids = {n["id"] for n in graph["nodes"]}
        self.assertIn("crm.lead,%d" % lead.id, ids)
        graph = self.env["pmk.flow.builder"].get_flow_graph("crm.lead", lead.id)
        self.assertIn("pmk.butik.spec,%d" % spec.id, {n["id"] for n in graph["nodes"]})
        lanes = self.env["pmk.flow.builder"].get_flow_lanes("crm.lead", lead.id)
        self.assertTrue(lanes["lanes"])

    def test_save_button(self):
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        action = spec.action_butik_save()
        self.assertEqual(action["tag"], "display_notification")
        self.assertIn(spec.name, action["params"]["message"])

    def test_easter_egg(self):
        spec = self.env["pmk.butik.spec"].create({"subject": "Тест"})
        product = spec.butik_rows()["rows"][0]
        rows = spec.butik_save_row(product["id"], {"name": "  Бутик   ЛОХ! "})["rows"]
        self.assertEqual(rows[0]["name"], "Сам ты лох")
        # название изделия не расшифровывается как деталь
        rows = spec.butik_save_row(product["id"], {"name": "Ограждение ОЛ-1 10шт"})["rows"]
        self.assertEqual((rows[0]["name"], rows[0]["product_qty"]), ("Ограждение ОЛ-1 10шт", 1))
        # у детали — не пасхалка
        detail = rows[1]
        rows = spec.butik_save_row(detail["id"], {"name": "бутик лох"})["rows"]
        self.assertEqual(rows[1]["name"], "бутик лох")

    def test_link_deal(self):
        lead = self.env["crm.lead"].create({"name": "Сделка бутика", "type": "opportunity"})
        spec = self.env["pmk.butik.spec"].create({"lead_id": lead.id})
        self.assertEqual(spec.lead_id, lead)
        self.assertTrue(spec.name.startswith("БТ-"))

    def test_move_product_block(self):
        """№312: в Бутике изделие перетаскивается вместе со своими деталями."""
        doc = self.env["pmk.butik.spec"].create({})
        doc.line_ids.unlink()
        Line = self.env["pmk.butik.line"]
        rows = [("product", "А", 10), ("detail", "а1", 20), ("product", "Б", 30), ("detail", "б1", 40)]
        recs = {n: Line.create({"spec_id": doc.id, "kind": k, "name": n, "sequence": s}) for k, n, s in rows}
        doc.butik_move_row(recs["Б"].id, recs["А"].id, False)
        self.assertEqual(doc.line_ids.sorted("sequence").mapped("name"), ["Б", "б1", "А", "а1"])
        doc.butik_move_row(recs["а1"].id, recs["б1"].id, True)
        self.assertEqual(doc.line_ids.sorted("sequence").mapped("name"), ["Б", "б1", "а1", "А"])
