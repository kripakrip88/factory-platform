# -*- coding: utf-8 -*-
"""Вентзонты: перенос генератора 51/51, заказ из нескольких размеров, чертёж."""

import base64
import io
import re
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.pmk_calc.tools import vent_hood as V
from odoo.addons.pmk_calc.tools import vent_hood_drawing as D

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.dirname(HERE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@tagged("post_install", "-at_install")
class TestVentHood(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Sheet = cls.env["pmk.metal.sheet"]

        def sheet(t):
            found = Sheet.search([("sheet_type", "=", "Оцинкованный"),
                                  ("thickness_mm", "=", t)], limit=1)
            return found or Sheet.create({
                "sheet_type": "Оцинкованный", "thickness_mm": t, "gost": "ГОСТ 14918-2020",
                "mass_per_sqm": t * 7.85})

        cls.sheet065 = sheet(0.65)
        cls.sheet05 = sheet(0.5)
        cls.ral = cls.env.ref("pmk_calc.coating_ral8017")
        cls.zinc = cls.env.ref("pmk_calc.coating_zinc")

    def _order(self, *sizes):
        lines = [(0, 0, dict({"coating_id": self.zinc.id}, **s)) for s in sizes]
        return self.env["pmk.vent.hood.order"].create({"line_ids": lines})

    def test_golden_51_of_51(self):
        """Перенос как есть: проверка генератора по 51 эталону (README, раздел 6)."""
        tmp = tempfile.mkdtemp()
        try:
            root = os.path.join(tmp, "g")
            shutil.copytree(os.path.join(HERE, "vent_hood_golden"), root)
            res = subprocess.run(
                [sys.executable, os.path.join(root, "tests", "check_golden.py"),
                 "--module", os.path.join(MODULE, "tools", "vent_hood.py")],
                capture_output=True, text=True, timeout=600)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("совпало 51 из 51", res.stdout)

    def test_standard_065_and_color_required(self):
        line = self._order({"width": 750, "length": 4000}).line_ids
        self.assertEqual(line.sheet_id, self.sheet065, "Стандарт — 0,65 мм.")
        self.assertEqual(line.thickness, 0.65)
        self.assertFalse(self.env["pmk.vent.hood"].default_get(["coating_id"]).get("coating_id"),
                         "Цвет без умолчания — выбирают всегда.")
        self.assertTrue(self.env["pmk.vent.hood"]._fields["coating_id"].required)
        with self.assertRaises(Exception):
            with self.cr.savepoint():
                self.env["pmk.vent.hood.order"].create(
                    {"line_ids": [(0, 0, {"width": 600, "length": 2400})]})

    def test_spec_is_generator_answer(self):
        line = self._order({"width": 750, "length": 4000, "coating_id": self.ral.id,
                            "sheet_id": self.sheet05.id}).line_ids
        expected = V.spec(V.hood(750, 4000), 0.5, "8017")
        self.assertEqual(json.loads(line.spec_json),
                         json.loads(json.dumps(expected, ensure_ascii=False)))
        self.assertEqual((line.lapki, line.klepki), (28, 24))
        self.assertEqual(line.subtitle,
                         "вш 750х4000 · Лист оцинкованный с полимерным покрытием RAL 8017 0.5 мм")
        self.assertIn("окрашенный лист", line.warnings_text)
        self.assertIn("Крышка торцевая", line.spec_html)

    def test_several_sizes_totals(self):
        order = self._order({"width": 750, "length": 4000, "qty": 2},
                            {"width": 1000, "length": 1200, "qty": 3},
                            {"width": -100, "length": 900})
        self.assertTrue(order.name.startswith("ВЗ-"))
        good = order.line_ids.filtered("spec_json")
        self.assertEqual(len(good), 2)
        self.assertEqual(order.total_positions, 3)
        self.assertEqual(order.total_qty, 6)
        self.assertTrue(order.has_errors, "Невозможный размер — ошибка видна на заказе.")
        self.assertAlmostEqual(order.total_mass_net_kg,
                               sum(l.mass_net_kg * l.qty for l in good), places=3)
        self.assertAlmostEqual(order.total_sheet_1250_m,
                               sum(l.sheet_1250_m * l.qty for l in good), places=3)

    def test_bad_size_is_error_not_drawing(self):
        line = self._order({"width": -100, "length": 900}).line_ids
        self.assertIn("> 0", line.spec_error)
        self.assertFalse(line.spec_json)
        self.assertFalse(line.drawing_png)
        with self.assertRaises(UserError):
            line.action_download_dxf()
        with self.assertRaises(UserError):
            line.action_download_png()

    def test_dxf_download(self):
        order = self._order({"width": 750, "length": 4000, "coating_id": self.ral.id,
                             "sheet_id": self.sheet05.id})
        line = order.line_ids
        action = line.action_download_dxf()
        line.action_download_dxf()
        att = self.env["ir.attachment"].search([("res_model", "=", order._name),
                                                ("res_id", "=", order.id)])
        self.assertEqual(len(att), 1, "Повторное скачивание не плодит копии.")
        self.assertEqual(att.name, "vsh_750x4000_t0.5_RAL8017.dxf")
        self.assertEqual(att.raw.decode("utf-8"), V.to_dxf(V.hood(750, 4000)))
        self.assertIn("/web/content/", action["url"])

    def test_drawing_is_generator_drawing(self):
        line = self._order({"width": 750, "length": 4000, "coating_id": self.ral.id}).line_ids
        png = base64.b64decode(line.drawing_png)
        self.assertTrue(png.startswith(PNG_MAGIC))
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            D.main(750, 4000, path, 0.65, "8017")
            with open(path, "rb") as fh:
                self.assertEqual(png, fh.read(), "Чертёж — ровно тот, что рисует генератор.")
        finally:
            os.unlink(path)
        line.action_download_png()
        att = self.env["ir.attachment"].search([("res_model", "=", "pmk.vent.hood.order"),
                                                ("res_id", "=", line.order_id.id)])
        self.assertRegex(att.name, r"^vsh_750x4000_t0\.65_RAL8017_чертёж_\d\d\.\d\d\.\d\d_\d\d-\d\d\.png$", "дата и время в имени")
        line.action_download_png()
        self.assertEqual(len(self.env["ir.attachment"].search([("res_model", "=", "pmk.vent.hood.order"),
                                                               ("res_id", "=", line.order_id.id)])), 1,
                         "повторное скачивание заменяет прежний файл, а не копит")
        line.action_download_dxf()
        self.assertIn("vsh_750x4000_t0.65_RAL8017.dxf",
                      self.env["ir.attachment"].search([("res_model", "=", "pmk.vent.hood.order"),
                                                        ("res_id", "=", line.order_id.id)]).mapped("name"),
                      "DXF — без даты: по имени CypCut называет детали")

    def test_download_all_zip(self):
        order = self._order({"width": 750, "length": 4000},
                            {"width": 600, "length": 2400, "coating_id": self.ral.id},
                            {"width": -100, "length": 900})
        order.action_download_all()
        att = self.env["ir.attachment"].search([("res_model", "=", order._name),
                                                ("res_id", "=", order.id)])
        self.assertRegex(att.name, r"^%s_\d\d\.\d\d\.\d\d_\d\d-\d\d\.zip$" % re.escape(order.name))
        names = sorted(zipfile.ZipFile(io.BytesIO(att.raw)).namelist())
        self.assertEqual(names, sorted([
            "vsh_750x4000_t0.65_оц.dxf", "vsh_750x4000_t0.65_оц_чертёж.png",
            "vsh_600x2400_t0.65_RAL8017.dxf", "vsh_600x2400_t0.65_RAL8017_чертёж.png",
            "%s_сборка.xlsx" % order.name]),
            "Размер с ошибкой в архив не попадает.")
        with self.assertRaises(UserError):
            self._order({"width": -100, "length": 900}).action_download_all()

    def test_open_line_and_name(self):
        order = self._order({"width": 750, "length": 4000}, {"width": -100, "length": 900})
        good, bad = order.line_ids.sorted("id")
        action = good.action_open_line()
        self.assertEqual((action["res_id"], action["target"]), (good.id, "new"))
        self.assertEqual(good.display_name, "вш 750х4000")
        self.assertEqual(bad.display_name, "Размер -100×900")

    def test_assembly_xlsx(self):
        import openpyxl
        order = self._order({"width": 750, "length": 4000, "qty": 2, "coating_id": self.ral.id},
                            {"width": 1000, "length": 1000, "qty": 3},
                            {"width": -100, "length": 900})
        order.partner_id = self.env["res.partner"].create({"name": "Тест Сборка"})
        order.action_download_assembly()
        att = self.env["ir.attachment"].search([("res_model", "=", order._name),
                                                ("res_id", "=", order.id)])
        self.assertRegex(att.name, r"^%s_сборка_\d\d\.\d\d\.\d\d_\d\d-\d\d\.xlsx$" % re.escape(order.name))
        wb = openpyxl.load_workbook(io.BytesIO(att.raw), data_only=True)
        ws = wb["Сборка"]
        rows = [[c.value for c in r] for r in ws.iter_rows()]
        flat = [v for r in rows for v in r if v is not None]
        self.assertIn("Контрагент: Тест Сборка", flat)
        head = next(r for r in rows if r[0] == "№")
        self.assertEqual(head[1:3], ["Зонт, мм", "Шахта, мм"], "Габарит зонта — первым (номенклатура склада).")
        self.assertEqual(head[6:14], ["Деталь", "Заготовка, мм", "Деталей на зонт", "Деталей всего",
                                      "Лапок на зонт", "Лапок всего", "Клёпок на зонт", "Клёпок всего"])
        good = order.line_ids.filtered("spec_json").sorted(lambda l: (l.sequence, l.id))
        hoods = [r for r in rows if isinstance(r[0], int)]
        self.assertEqual([r[1] for r in hoods], ["4300 × 1050", "1300 × 1300"], "Шахта + 150 с каждой стороны.")
        self.assertEqual([r[2] for r in hoods], ["4000 × 750", "1000 × 1000"])
        for r, line in zip(hoods, good):
            self.assertEqual((r[5], r[10], r[11], r[12], r[13]),
                             (line.qty, line.lapki, line.lapki * line.qty,
                              line.klepki, line.klepki * line.qty))
        parts = [r for r in rows if r[6] in ("Крышка торцевая", "Панель торцевая",
                                             "Панель средняя", "Тело зонта")]
        self.assertEqual(len(parts), sum(len(l._vh_spec()["parts"]) for l in good))
        self.assertIn("449,6 × 1058,5", [r[7] for r in parts])
        total = next(r for r in rows if r[0] == "ИТОГО")
        self.assertEqual(total[5], 5)
        self.assertEqual(total[11], sum(l.lapki * l.qty for l in good))
        self.assertEqual(total[13], sum(l.klepki * l.qty for l in good))
        self.assertTrue(any(str(v).startswith("Не вошёл: Размер -100×900") for v in flat))
        merged = [str(m) for m in ws.merged_cells.ranges]
        top = rows.index(hoods[0]) + 1
        self.assertIn("B%d:B%d" % (top, top + 2), merged, "Зонт — одна ячейка на высоту деталей.")
        self.assertEqual(good[0].hood_size, "4300 × 1050")
        self.assertEqual(good[0].shaft_size, "4000 × 750")
        order.action_download_all()
        zip_att = self.env["ir.attachment"].search([("res_model", "=", order._name),
                                                    ("res_id", "=", order.id),
                                                    ("name", "=like", "%.zip")])
        self.assertIn("%s_сборка.xlsx" % order.name,
                      zipfile.ZipFile(io.BytesIO(zip_att.raw)).namelist())

    def test_sides_swapped_automatically(self):
        line = self._order({"width": 1200, "length": 900}).line_ids
        self.assertEqual((line.width, line.length), (900, 1200))
        self.assertTrue(line.sides_swapped)
        self.assertFalse(line.spec_error)
        self.assertEqual(line.hood_label, "вш 900х1200")
        line.write({"length": 1500})
        self.assertEqual((line.width, line.length), (900, 1500))
        self.assertFalse(line.sides_swapped, "Ввели как надо — отметки нет.")
        line.write({"width": 2000})
        self.assertEqual((line.width, line.length, line.sides_swapped), (1500, 2000, True))
        square = self._order({"width": 1000, "length": 1000}).line_ids
        self.assertFalse(square.sides_swapped)
        draft = self.env["pmk.vent.hood"].new({"width": 1300, "length": 1100})
        draft._onchange_sides()
        self.assertEqual((draft.width, draft.length, draft.sides_swapped), (1100, 1300, True))

    def test_order_form_expands_composition(self):
        arch = self.env["pmk.vent.hood.order"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn('widget="pmk_vent_hood_lines"', arch)
        for name in ("spec_json", "warnings_text", "material_name", "lapki", "klepki"):
            self.assertIn('name="%s"' % name, arch, "Разворот берёт %s из строки." % name)
        self.assertNotIn("action_open_line", arch, "Окно «Детали» заменено разворотом.")

    def test_change_size_recomputes(self):
        line = self._order({"width": 750, "length": 4000}).line_ids
        before = line.klepki
        line.write({"width": 1250, "length": 1600})
        self.assertEqual(line.hood_label, "вш 1250х1600")
        self.assertNotEqual(line.klepki, before)

    def test_sheet_list_is_galvanized_only(self):
        field = self.env["pmk.vent.hood"]._fields["sheet_id"]
        self.assertEqual(field.domain, [("sheet_type", "=", "Оцинкованный")])
        self.assertEqual(self.env["pmk.dobor.order.line"]._fields["sheet_id"].domain, field.domain,
                         "Список металла — тот же, что у доборки.")

    def test_forms_open_for_employee(self):
        user = self.env["res.users"].create({
            "name": "Сотрудник ВЗ", "login": "vh_employee",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        Order = self.env["pmk.vent.hood.order"].with_user(user)
        views = Order.get_views([(False, "form"), (False, "list"), (False, "search")])
        self.assertIn("action_download_all", views["views"]["form"]["arch"])
        line_form = self.env["pmk.vent.hood"].with_user(user).get_views([(False, "form")])
        self.assertIn("drawing_png", line_form["views"]["form"]["arch"])
        order = Order.create({"line_ids": [(0, 0, {"width": 600, "length": 2400,
                                                   "coating_id": self.zinc.id})]})
        self.assertTrue(order.line_ids.spec_json)

    def test_sves_parameter(self):
        """Свес — параметр строки (12.10.2026): 150 по умолчанию; меньший доходит до заготовок."""
        order = self._order({"width": 750, "length": 4000})
        line = order.line_ids
        self.assertEqual(line.sves, 150)
        std = line._vh_spec()
        self.assertEqual(line.hood_size, "4300 × 1050")
        self.assertEqual(line._vh_dxf(), line._vh_dxf_standard())
        line.sves = 130
        self.assertEqual(line.hood_size, "4260 × 1010")
        self.assertNotEqual(line._vh_spec(), std, "заготовки пересчитаны под свес")
        self.assertNotEqual(line._vh_dxf(), line._vh_dxf_standard())
        self.assertIn("свес торцов 130", line.warnings_text or "")
        for bad in (120, 160):
            with self.assertRaises(ValidationError):
                line.sves = bad


@tagged("post_install", "-at_install")
class TestVentHoodDrawingUrl(HttpCase):

    def test_drawing_served_as_image(self):
        """Окно «Чертёж» берёт картинку по /web/image/pmk.vent.hood/<id>/drawing_png."""
        sheet = self.env["pmk.metal.sheet"].search([("sheet_type", "=", "Оцинкованный")], limit=1)
        order = self.env["pmk.vent.hood.order"].create({"line_ids": [(0, 0, {
            "width": 750, "length": 4000, "sheet_id": sheet.id,
            "coating_id": self.env.ref("pmk_calc.coating_zinc").id})]})
        self.authenticate("admin", "admin")
        res = self.url_open("/web/image/pmk.vent.hood/%s/drawing_png" % order.line_ids.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Type"), "image/png")
        self.assertTrue(res.content.startswith(PNG_MAGIC))

