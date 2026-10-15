# -*- coding: utf-8 -*-
"""Переделка лазера 15.10.2026: задание на резку по заказу (ЗР) → «Детали к раскрою» →
раскрой (РС) из деталей нескольких заказов; чертежи пачкой с разбором «пл1 10мм 20шт»."""
import base64
import hashlib
import io

import ezdxf

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.task import parse_file_name


def _dxf(w=100.0, h=60.0, hole=8.0):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True)
    if hole:
        msp.add_circle((w / 2, h / 2), hole)
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


@tagged("post_install", "-at_install")
class TestFileNames(TransactionCase):

    def test_names(self):
        self.assertEqual(parse_file_name("пл1 10мм 20шт.dxf"), ("пл1", 10.0, 20))
        self.assertEqual(parse_file_name("0,45мм шаблон 6шт.dxf"), ("шаблон", 0.45, 6))
        self.assertEqual(parse_file_name("2мм Лоток 284х260х2 L=1250мм - 269шт.dxf"),
                         ("Лоток 284х260х2 L=1250мм", 2.0, 269))
        self.assertEqual(parse_file_name("шайба 2мм.dxf"), ("шайба", 2.0, None))
        self.assertEqual(parse_file_name("Полка - левая 3мм.dxf"), ("Полка - левая", 3.0, None))
        self.assertEqual(parse_file_name("кронштейн (4).dxf"), ("кронштейн", None, 4))


@tagged("post_install", "-at_install")
class TestLaserTasks(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True,
                                       mail_create_nolog=True, mail_create_nosubscribe=True))
        Sheet = cls.env["pmk.metal.sheet"]
        for t in (2.0, 10.0):
            if not Sheet.search([("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", t)], limit=1):
                Sheet.create({"sheet_type": "Гладкий", "thickness_mm": t, "gost": "ГОСТ 19903-2015",
                              "mass_per_sqm": 7.85 * t})
        cls.machine = cls.env["pmk.laser.machine"].create({"name": "Станок-проба ЗР", "max_thickness_mm": 20})
        cls.dxf = base64.b64encode(_dxf())
        cls.dxf2 = base64.b64encode(_dxf(80, 40, 0))

    def _task(self, *parts, **vals):
        task = self.env["pmk.laser.task"].create(dict({"note": "проба"}, **vals))
        for name, t, qty in parts:
            self.env["pmk.laser.task.part"].create({
                "task_id": task.id, "name": name, "thickness_mm": t, "qty": qty,
                "drawing": self.dxf, "drawing_name": name + ".dxf"})
        return task

    def test_task_number_and_parse(self):
        task = self._task(("пл1", 10, 20))
        self.assertTrue(task.name.startswith("ЗР-"))
        part = task.part_ids
        part.action_parse_drawing()
        self.assertGreater(part.cut_length_mm, 300, "контур 100×60 + отверстие")
        self.assertEqual(part.pierce_count, 2)
        self.assertEqual(part.size_text, "100 × 60")
        self.assertEqual(task.thickness_text, "10 мм")

    def _nest(self, parts):
        action = parts.action_create_nest()
        self.assertEqual(action["res_model"], "pmk.laser.nest")
        return self.env["pmk.laser.nest"].browse(action["res_id"])

    def test_nest_from_two_orders(self):
        a = self._task(("пл1", 2, 20), ("косынка", 2, 40), ("пл2", 10, 4))
        b = self._task(("пл1", 2, 6))
        parts = (a.part_ids | b.part_ids).filtered(lambda p: p.thickness_mm == 2)
        nest = self._nest(parts)
        self.assertTrue(nest.name.startswith("РС-"))
        job = nest.program_ids
        self.assertEqual(len(job), 1)
        self.assertEqual(job.name, "%s · 2 мм" % nest.name)
        self.assertAlmostEqual(job.thickness_mm, 2.0)
        self.assertEqual(job.task_ids, a | b, "в раскрое детали двух заказов")
        names = sorted(job.part_ids.mapped("name"))
        self.assertEqual(len(names), 3)
        self.assertIn("пл1 (%s)" % b.name, names, "одинаковые «пл1» двух заказов — разные имена в программе")
        self.assertEqual(a.part_ids.filtered(lambda p: p.name == "косынка").qty_left, 0)
        self.assertEqual(a.part_ids.filtered(lambda p: p.name == "пл2").qty_left, 4, "10 мм — не тронута")
        self.assertEqual(a.state, "nest")
        self.assertIn(job, a.job_ids)
        self.assertEqual(nest.task_ids, a | b)

    def test_one_nest_many_thicknesses(self):
        """Один раскрой — программа на каждую толщину (как цвета у зонтов)."""
        a = self._task(("пл1", 2, 20), ("пл2", 10, 4), ("пл3", 10, 2))
        nest = self._nest(a.part_ids)
        self.assertEqual(sorted(round(t, 1) for t in nest.program_ids.mapped("thickness_mm")), [2.0, 10.0])
        ten = nest.program_ids.filtered(lambda p: p.thickness_mm == 10)
        self.assertEqual(len(ten.part_ids), 2)
        self.assertEqual(nest.thickness_text, "2 мм, 10 мм")
        self.assertEqual(nest.state, "draft")
        b = self._task(("косынка", 10, 8))
        b.part_ids.with_context(pmk_target_nest=nest.id).action_create_nest()
        self.assertEqual(len(ten.part_ids), 3, "добавили в тот же раскрой — в программу своей толщины")
        c = self._task(("лоток", 2, 5))
        self.assertEqual(c.action_nest_all()["res_model"], "pmk.laser.nest")
        self.assertEqual(c.part_ids.qty_left, 0)

    def test_nest_checks(self):
        a = self._task(("пл1", 2, 20), ("пл2", 3.7, 4))
        with self.assertRaisesRegex(UserError, "Нет листа в справочнике"):
            a.part_ids.action_create_nest()
        a.part_ids[0].drawing = False
        with self.assertRaisesRegex(UserError, "Нет чертежа"):
            a.part_ids[0].action_create_nest()

    def test_partial_qty_and_add_to_nest(self):
        a = self._task(("лоток", 2, 269))
        nest = self._nest(a.part_ids)
        job = nest.program_ids
        line = job.part_ids
        line.qty = 100
        self.assertEqual(a.part_ids.qty_left, 169, "остаток — снова в «Детали к раскрою»")
        with self.assertRaisesRegex(UserError, "уменьшите количество"):
            line.qty = 300
        b = self._task(("шайба", 2, 16))
        wiz = self.env["pmk.laser.add.to.nest"].with_context(
            **b.part_ids.action_add_to_nest()["context"]).create({"nest_id": nest.id})
        wiz.action_apply()
        self.assertEqual(len(job.part_ids), 2)
        self.assertEqual(job.task_ids, a | b)

    def test_upload_preview_and_apply(self):
        task = self._task(("пл1", 10, 20))
        same = hashlib.sha1(base64.b64decode(self.dxf)).hexdigest()
        other = hashlib.sha1(base64.b64decode(self.dxf2)).hexdigest()
        rows = task.pmk_upload_preview([
            {"name": "пл1 10мм 20шт.dxf", "sha1": same, "folder": ""},
            {"name": "пл1 10мм 4шт.dxf", "sha1": other, "folder": "Изделие Б"},
            {"name": "косынка 2мм.dxf", "sha1": other, "folder": ""},
            {"name": "опора.lxds.fs.emf", "sha1": "x", "folder": ""},
        ])
        self.assertEqual(rows[0]["conflict"], "same")
        self.assertEqual(rows[0]["action"], "skip")
        self.assertEqual(rows[1]["conflict"], "name")
        self.assertEqual(rows[1]["alt_name"], "Изделие Б · пл1")
        self.assertTrue(rows[2]["qty_missing"])
        self.assertEqual(rows[2]["thickness"], 2.0)
        self.assertTrue(rows[3]["skip"])
        res = task.pmk_upload_apply([
            dict(rows[1], data=self.dxf2, action="new", file="пл1 10мм 4шт.dxf"),
            dict(rows[2], data=self.dxf2, action="new", qty=12, file="косынка 2мм.dxf"),
        ])
        self.assertEqual(res["created"], 2)
        names = sorted(task.part_ids.mapped("name"))
        self.assertEqual(names, ["Изделие Б · пл1", "косынка", "пл1"])
        kos = task.part_ids.filtered(lambda p: p.name == "косынка")
        self.assertEqual((kos.qty, kos.thickness_mm), (12, 2.0))
        self.assertGreater(kos.cut_length_mm, 0, "чертёж разобран сразу")
        self.assertEqual(task.thickness_text, "2 мм, 10 мм")

    def test_job_line_parse_drawing_fixed(self):
        """«Разобрать» в строке раскроя падала: звала несуществующий drawing.read_drawing."""
        a = self._task(("пл1", 2, 5))
        job = self._nest(a.part_ids).program_ids
        job.part_ids.write({"cut_length_mm": 0})
        job.part_ids.action_parse_drawing()
        self.assertGreater(job.part_ids.cut_length_mm, 0)

    def test_menus(self):
        names = self.env.ref("pmk_laser.menu_pmk_laser").child_id.mapped("name")
        for n in ("Задания на резку", "Детали к раскрою", "Раскрои", "Программы раскроя", "Очередь листов"):
            self.assertIn(n, names)

    def test_machine_choice_air_first(self):
        """Воздух дешевле кислорода: 3 кВт режет на воздухе до 6 мм, 20 кВт — до 20 мм (Антон 15.10)."""
        M = self.env["pmk.laser.machine"]
        M.search([]).write({"active": False})
        small = M.create({"name": "Лазер 3 кВт", "power_kw": 3, "max_thickness_mm": 20, "air_max_thickness_mm": 6,
                          "max_width_mm": 1500, "max_length_mm": 3000, "sheet_tolerance_mm": 5})
        big = M.create({"name": "Лазер 20 кВт", "power_kw": 20, "max_thickness_mm": 60,
                        "air_max_thickness_mm": 20, "max_width_mm": 2000, "max_length_mm": 12500})
        self.assertEqual(M._for_thickness(2), small)
        self.assertEqual(M._for_thickness(6), small)
        self.assertEqual(M._for_thickness(10), big, "10 мм: 20 кВт на воздухе дешевле, чем 3 кВт кислородом")
        self.assertEqual(M._for_thickness(40), big)
        self.assertTrue(small._fits_sheet(1505, 3005))
        self.assertFalse(small._fits_sheet(1510, 3010))
        self.assertTrue(big._fits_sheet(2000, 6000))

