# -*- coding: utf-8 -*-
"""«Конструкции» — таблица Бутика в составе расчёта (20.10.2026)."""
from lxml import etree

from odoo.tests import TransactionCase, tagged


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
