# -*- coding: utf-8 -*-
"""«Конструкции» — таблица Бутика в составе расчёта (20.10.2026)."""
from lxml import etree

from odoo.tests import TransactionCase, tagged

from ..tools import parse


@tagged("post_install", "-at_install")
class TestKonstr(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест конструкций)"})
        cls.angle = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест конструкций)", "gost": "ГОСТ",
            "size_label": "63x4", "mass_per_meter": 3.9})
        cls.spec = cls.env["pmk.metal.spec"].create({"note": "Конструкции"})

    def _rows(self, data=None):
        return (data or self.spec.konstr_rows())["rows"]

    def _detail(self, rows):
        return [r for r in rows if r["kind"] == "detail"]

    def test_product_and_detail(self):
        data = self.spec.konstr_add_product()
        rows = self._rows(data)
        product, detail = rows[0], rows[1]
        self.assertEqual((product["kind"], product["name"], detail["parent"]), ("product", "Изделие 1", product["id"]))
        rows = self._rows(self.spec.konstr_save_row(product["id"], {"name": "Ограждение ОЛ-1", "product_qty": "3",
                                                                      "price": "48200"}))
        self.assertEqual((rows[0]["name"], rows[0]["product_qty"], rows[0]["price"]), ("Ограждение ОЛ-1", 3, 48200))
        rows = self._rows(self.spec.konstr_save_row(detail["id"], {"name": self.angle.display_name}))
        rows = self._rows(self.spec.konstr_save_row(detail["id"], {"length_mm": "1000", "qty": "2", "pos": "д1"}))
        line = self.spec.product_ids.line_ids
        self.assertEqual((line.calc_mode, line.length_mm, line.qty, line.detail_name), ("linear", 1000, 2, "д1"))
        self.assertTrue(line.profile_id, "Наименование распознано позицией справочника.")
        row = self._detail(rows)[0]
        self.assertEqual(row["qty_total"], 6, "Всего = на 1 шт × изделий.")
        self.assertAlmostEqual(row["weight_total"], line.weight_total * 3, places=3)

    def test_short_line_sheet_and_grade(self):
        rows = self._rows(self.spec.konstr_add_product())
        detail = self._detail(rows)[0]
        rows = self._rows(self.spec.konstr_save_row(detail["id"], {"name": "т1 10мм 100х200мм 4шт ст3"}))
        line = self.spec.product_ids.line_ids
        self.assertEqual((line.calc_mode, line.a_mm, line.b_mm, line.qty, line.detail_name),
                         ("sheet", 100, 200, 4, "Т1"))
        self.assertEqual(line.pmk_text, "Лист 10")
        row = self._detail(rows)[0]
        self.assertTrue(row["is_sheet"])
        self.assertEqual((row["width"], row["length_mm"]), (100, 200))
        self.assertEqual(row["grade"], line.grade_id.name or line.pmk_grade_text)
        # Марки нет в справочнике — текстом, не теряется.
        self.spec.konstr_save_row(detail["id"], {"grade": "Неведомая-99"})
        self.assertEqual((line.grade_id.id, line.pmk_grade_text), (False, "Неведомая-99"))

    def test_paste_and_insert_after_product(self):
        rows = self._rows(self.spec.konstr_add_product())
        product, empty = rows[0], rows[1]
        rows = self._rows(self.spec.konstr_insert_rows(empty["id"], [
            {"pos": "1", "name": self.angle.display_name, "length_mm": "500", "qty": "2", "grade": ""},
            {"name": "пл2 200х140х20мм 3шт"},
        ]))
        details = self._detail(rows)
        self.assertEqual(len(details), 2, "Пустая строка уступила место вставленным.")
        self.assertEqual(details[0]["pos"], "1")
        self.assertEqual(details[1]["pos"], "Пл2")
        # Новая строка после изделия — первой в нём.
        rows = self._rows(self.spec.konstr_save_row(False, {"after_id": product["id"]}))
        self.assertEqual(rows[1]["name"], "")
        self.assertEqual(len(self._detail(rows)), 3)

    def test_choose_position_and_delete(self):
        rows = self._rows(self.spec.konstr_add_product())
        detail = self._detail(rows)[0]
        self.spec.konstr_save_row(detail["id"], {"name": "что-то непонятное"})
        row = self._detail(self.spec.konstr_rows()["rows"])[0]
        self.assertEqual(row["match_state"], "none")
        rows = self._rows(self.spec.konstr_set_position(detail["id"], "profile:%d" % self.angle.id))
        self.assertEqual(self.spec.product_ids.line_ids.profile_id, self.angle)
        self.assertEqual(self._detail(rows)[0]["match_state"], "auto")
        self.spec.konstr_duplicate_row(rows[0]["id"])
        self.assertEqual(len(self.spec.product_ids), 2, "Копия изделия — с деталями.")
        rows = self._rows(self.spec.konstr_delete_row(self.spec.konstr_rows()["rows"][0]["id"]))
        self.assertEqual(len(self.spec.product_ids), 1)

    def test_old_lines_show_reference_name(self):
        """Старые строки (без набранного текста) — наименование из справочника."""
        self.spec.write({"product_ids": [(0, 0, {"name": "Старое", "qty": 1, "line_ids": [(0, 0, {
            "calc_mode": "linear", "profile_id": self.angle.id, "length_mm": 700, "qty": 1})]})]})
        row = self._detail(self.spec.konstr_rows()["rows"])[0]
        self.assertEqual(row["name"], self.angle.display_name)
        self.assertEqual(row["length_mm"], 700)

    def test_view(self):
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_views([(False, "form")])["views"]["form"]["arch"])
        page = arch.xpath("//page[@name='composition']")[0]
        children = [c.get("name") for c in page]
        self.assertEqual(children[:2], ["pmk_konstr_grid", "product_ids"],
                         "Таблица — над прежним редактором, редактор на месте (xpath модулей).")

    # ─── №307: по массе из спецификации КМ ──────────────────────────────
    def test_km_short_entry(self):
        cases = {
            "шв10 12,43тн": ("Швеллер 10", 12430.0),
            "шв10 12.43 т": ("Швеллер 10", 12430.0),
            "Гн.Р180х8 2516,4кг С345": ("Труба профильная 180х180х8", 2516.4),
            "Гн.Р160х100х6 5423,2кг": ("Труба профильная 160х100х6", 5423.2),
            "I30Ш1 2293,6кг": ("Двутавр 30Ш1", 2293.6),
            "L80x6 115,3кг": ("Уголок 80х6", 115.3),
            "t20 556,3кг с345": ("Лист 20", 556.3),
        }
        for text, (name, mass) in cases.items():
            with self.subTest(text=text):
                dec = parse.decode_for_cell(text)
                self.assertEqual((dec["name"], dec["mass_kg"]), (name, mass))
        # Прежние записи — как были.
        self.assertEqual(parse.decode_for_cell("шв10п 600 мм 2 шт")["name"], "Швеллер 10П")
        self.assertEqual(parse.decode_for_cell("уг80х6 1500мм")["length_mm"], 1500.0)
        self.assertIsNone(parse.decode_for_cell("Уголок 63х4"))

    def test_mass_line_and_price_per_ton(self):
        rows = self._rows(self.spec.konstr_add_product())
        product, detail = rows[0], rows[1]
        self.spec.konstr_save_row(detail["id"], {"name": self.angle.display_name})
        rows = self._rows(self.spec.konstr_save_row(detail["id"], {"mass": "390"}))
        line = self.spec.product_ids.line_ids
        self.assertEqual(line.pmk_mass_kg, 390)
        self.assertAlmostEqual(line.weight_total, 390, places=3)
        self.assertAlmostEqual(line.length_mm, 100000, places=0, msg="Длина — из массы: 390 / 3,9 кг/м.")
        row = self._detail(rows)[0]
        self.assertTrue(row["by_mass"] and row["length_derived"])
        self.assertIn("по КМ", row["label"])
        # Цена за т → цена за шт из веса изделия.
        rows = self._rows(self.spec.konstr_save_row(product["id"], {"price_ton": "200 000"}))
        prod = self.spec.product_ids
        self.assertEqual(prod.pmk_price_ton, 200000)
        self.assertAlmostEqual(prod.price_customer_unit, 78000, places=2)
        # Цена за шт руками — «за т» очищается.
        self.spec.konstr_save_row(product["id"], {"price": "90000"})
        self.assertEqual((prod.pmk_price_ton, prod.price_customer_unit), (0, 90000))
        # Изделий 2: «Вес всего» — на все, в строке — на одно.
        self.spec.konstr_save_row(product["id"], {"product_qty": "2"})
        self.spec.konstr_save_row(detail["id"], {"mass": "780"})
        self.assertAlmostEqual(line.pmk_mass_kg, 390, places=3)
        # Вписали длину — снова по размерам.
        self.spec.konstr_save_row(detail["id"], {"length_mm": "1000"})
        self.assertEqual((line.pmk_mass_kg, line.length_mm), (0, 1000))
        self.assertAlmostEqual(line.weight_total, 3.9, places=3)

    def test_mass_from_short_entry(self):
        """«уг 63 4 390кг» в ячейке — масса берётся из набранного (на копии 20.10
        терялась: читали уже расшифрованное наименование)."""
        detail = self._detail(self._rows(self.spec.konstr_add_product()))[0]
        self.spec.konstr_save_row(detail["id"], {"name": "уг 63 4 390кг"})
        line = self.spec.product_ids.line_ids
        self.assertEqual((line.pmk_text, line.pmk_mass_kg), ("Уголок 63х4", 390))
        self.assertAlmostEqual(line.weight_total, 390, places=3)
        self.spec.konstr_save_row(detail["id"], {"name": "шв10 1,5т"})
        self.assertEqual(line.pmk_mass_kg, 1500)

    def test_mass_sheet_not_laid_out(self):
        sheet = self.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест КМ)", "thickness_mm": 20.0, "gost": "ГОСТ", "mass_per_sqm": 157.0})
        self.spec.write({"product_ids": [(0, 0, {"name": "МК по КМ", "qty": 1, "line_ids": [
            (0, 0, {"calc_mode": "sheet", "sheet_id": sheet.id, "pmk_mass_kg": 314.0, "qty": 1}),
            (0, 0, {"calc_mode": "sheet", "sheet_id": sheet.id, "a_mm": 200, "b_mm": 300, "qty": 2})]})]})
        mass_line, size_line = self.spec.product_ids.line_ids.sorted("id")
        self.assertAlmostEqual(mass_line.weight_total, 314.0, places=3)
        self.spec.action_draft_layout()
        self.assertFalse(mass_line.layout_group_id, "Лист «по КМ» не раскладывается.")
        self.assertTrue(size_line.layout_group_id)
        buy = [r for r in self.spec._pmk_buy_rows() if r.get("source") == "по КМ"]
        self.assertEqual(len(buy), 1)
        self.assertAlmostEqual(buy[0]["kg"], 314.0, places=3)
        self.assertIn("2 м²", buy[0]["amount"], "314 кг / 157 кг/м² = 2 м².")

    def test_move_rows(self):
        """№312: перетащить — изделие с деталями среди изделий, деталь — в другое изделие."""
        Command = __import__("odoo").Command
        spec = self.env["pmk.metal.spec"].create({"note": "Перетаскивание", "product_ids": [
            Command.create({"name": "А", "sequence": 10, "line_ids": [
                Command.create({"detail_name": "а1", "sequence": 10}), Command.create({"detail_name": "а2", "sequence": 20})]}),
            Command.create({"name": "Б", "sequence": 20, "line_ids": [
                Command.create({"detail_name": "б1", "sequence": 10})]})]})
        a, b = spec.product_ids.sorted("sequence")
        spec.konstr_move_row("p%s" % b.id, "p%s" % a.id, False)
        self.assertEqual(spec._konstr_products().mapped("name"), ["Б", "А"])
        a1 = a.line_ids.filtered(lambda l: l.detail_name == "а1")
        b1 = b.line_ids
        spec.konstr_move_row("d%s" % a1.id, "d%s" % b1.id, True)
        self.assertEqual(a1.product_id, b)
        self.assertEqual(b.line_ids.sorted("sequence").mapped("detail_name"), ["б1", "а1"])
        self.assertEqual(a.line_ids.mapped("detail_name"), ["а2"])
