# -*- coding: utf-8 -*-
"""Закладные: запись строки, состав и массы, регрессия против выгрузки генератора,
DXF глазами раскроя листа, очередь чертежей (процесс подменён файлами), задание на резку.

Проверки самих PDF (2 листа, линия через надпись, техтребования в рамке) — там, где есть
PyMuPDF: tests/check_drawings.py в контейнере odoo-zk-worker.
"""
import base64
import csv
import io
import json
import os
import re
import sys
import zipfile
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..tools import catalog

DATA = os.path.join(os.path.dirname(__file__), "data")


@tagged("post_install", "-at_install")
class TestZkCatalog(TransactionCase):
    def test_parse_short_entry(self):
        p = catalog.parse("мн 201-5 12шт")
        self.assertEqual((p["mark"], p["series"], p["qty"], p["length"]), ("МН 201-5", "15", 12, 0.0))
        p = catalog.parse("мн 104-1 1200 10шт")
        self.assertEqual((p["mark"], p["length"], p["qty"], p["pogon"]), ("МН 104-1", 1200.0, 10, True))
        p = catalog.parse("м1-9-7 4шт")
        self.assertEqual((p["mark"], p["series"], p["qty"]), ("М1-9-7", "676", 4))
        self.assertEqual(catalog.parse("mh 201-5 x3")["qty"], 3, "латиница вместо кириллицы")
        self.assertEqual(catalog.parse("МН 104-6 L1200")["length"], 1200.0)
        self.assertIn("погонное", catalog.parse("мн 104-1")["error"])
        self.assertIn("не погонное", catalog.parse("мн 201-5 1200мм")["error"])
        self.assertIn("нет в сериях", catalog.parse("мн 999-1")["error"])
        self.assertIn("не понял", catalog.parse("мн 201-5 12шт ох")["error"])

    def test_regression_index(self):
        """Размеры, анкеры, длины стержней и массы — как в выгрузке генератора (index.csv), 786 изделий."""
        g = catalog.gen()
        checked = 0
        for name, series in (("index_15.csv", "15"), ("index_676.csv", "676"), ("index_15_pogon.csv", "15")):
            with open(os.path.join(DATA, name), encoding="utf-8-sig") as f:
                for r in csv.DictReader(f, delimiter=";"):
                    m = re.match(r"(.+?)(?: L(\d+))?$", r["Изделие"])
                    M, ms, why = catalog.model(series, m[1], float(m[2] or 0))
                    self.assertTrue(M, "%s: %s" % (r["Изделие"], why))
                    got = ("%s×%s×%s" % (g.fmt(M["A"]), g.fmt(M["B"]), g.fmt(M["t"])),
                           "; ".join("%d×Ø%s" % (len(G["pts"]), G["d"]) for G in M["groups"]),
                           "; ".join(g.fmt(G["rod"]) for G in M["groups"]), round(ms["all"], 2))
                    exp = (r["Пластина"], r["Анкеры"], r["L стержня"], float(r["Масса Т11-Мз, кг"]))
                    self.assertEqual(got, exp, r["Изделие"])
                    checked += 1
        self.assertEqual(checked, 786)

    def test_mass_against_series(self):
        """Масса против серии: 1.400-15 — ±5 % (кроме мелких МН 101–107: серия округляет до 0,1 кг),
        1.400-6/76 — ±6 %, где масса на листе прочитана."""
        out = []
        for key, (series, rec, pogon) in catalog.index().items():
            if pogon:
                continue
            mark = rec["Изделие"] if series == "15" else rec[0]["mark"]
            M, ms, _why = catalog.model(series, mark)
            if not M or not M.get("site_mass"):
                continue
            if series == "15" and re.match(r"МН 10[1-7]-", mark):
                continue
            limit = 0.05 if series == "15" else 0.06
            if abs(ms["all"] - M["site_mass"]) / M["site_mass"] > limit:
                out.append("%s: %.2f против %.2f" % (mark, ms["all"], M["site_mass"]))
        self.assertFalse(out, "\n".join(out))

    def test_dxf_read_by_sheet_nest(self):
        """DXF читается раскроем листа: один внешний контур; у поз. 2 МН 201–228 — отверстий
        и окружностей гравировки столько, сколько анкеров."""
        lib = self.env["ir.module.module"].search([("name", "=", "pmk_sheet_nest"), ("state", "=", "installed")])
        if not lib:
            self.skipTest("pmk_sheet_nest не установлен")
        from odoo.addons.pmk_sheet_nest.models.run import LIB_DIR
        if LIB_DIR not in sys.path:
            sys.path.insert(0, LIB_DIR)
        from sheet_nest.read_dxf import parts_from_dxf

        calc = self.env["pmk.zk.calc"].create({})
        for i, mark in enumerate(("МН 201-5", "МН 101-1", "МН 310-1", "М1-9-7")):
            res = catalog.parse(mark)
            self.env["pmk.zk.line"].create({"calc_id": calc.id, "sequence": i, "mark": res["mark"],
                                            "series": res["series"], "qty": 3})
        with zipfile.ZipFile(io.BytesIO(calc._zk_dxf_zip())) as zf:
            names = zf.namelist()
            self.assertIn("10 мм/МН 201-5_поз2_пластина_отв_10мм_3шт.dxf", names)
            for name in names:
                parts = parts_from_dxf(zf.read(name), os.path.basename(name))
                self.assertEqual(len(parts), 1, name)
                part = parts[0]
                self.assertFalse(part["warnings"], name)
                self.assertEqual(part["qty"], int(re.search(r"_(\d+)шт", name)[1]), name)
                self.assertEqual(sum(1 for s in part["shapes"] if s.get("outer")), 1, name)
                if "МН 201-5_поз2" in name:
                    holes = [s for s in part["shapes"] if not s.get("outer") and s["layer"] == 1]
                    grav = [s for s in part["shapes"] if s["layer"] != 1]
                    self.assertEqual((len(holes), len(grav)), (4, 4))


@tagged("post_install", "-at_install")
class TestZkDocument(TransactionCase):
    def setUp(self):
        super().setUp()
        self.calc = self.env["pmk.zk.calc"].create({"object_name": "Эстакада ТП-2"})

    def _type(self, key, text):
        return self.calc.zk_save_row(key, {"name": text})

    def test_grid_rows(self):
        data = self.calc.zk_rows()
        self.assertEqual(len(data["rows"]), 1, "новый документ — сразу пустая строка")
        self.assertTrue(self.calc.name.startswith("ЗК-"))
        key = data["rows"][0]["id"]
        data = self._type(key, "мн 201-5 12шт")
        row = data["rows"][0]
        self.assertEqual((row["name"], row["product_qty"], row["series"]), ("МН 201-5", 12, "1.400-15"))
        self.assertEqual(row["plate"], "2 × 150×150×10")
        self.assertAlmostEqual(row["mass"], 4.95, places=2)
        self.assertEqual([c["pos"] for c in row["comp"]], [1, 2, 3])
        data = self.calc.zk_save_row(False, {"after_id": key, "name": "мн 104-1 1200 10шт"})
        pogon = data["rows"][1]
        self.assertTrue(pogon["pogon"])
        self.assertEqual((pogon["name"], pogon["length"]), ("МН 104-1 L1200", 1200))
        data = self.calc.zk_save_row(pogon["id"], {"length": "2400"})
        self.assertEqual(data["rows"][1]["name"], "МН 104-1 L2400")
        data = self.calc.zk_insert_rows(data["rows"][1]["id"], [{"a": "мн 999-1", "b": "2"}, {"a": "МН 301-1"}])
        bad, unsupported = data["rows"][2], data["rows"][3]
        self.assertTrue(bad["bad"] and "нет в сериях" in bad["label"])
        self.assertEqual(bad["name"], "мн 999-1 2", "непонятая запись остаётся как набрали")
        self.assertTrue(unsupported["bad"] and "привязки" in unsupported["label"])
        self.assertEqual((self.calc.total_qty, self.calc.mark_count), (22, 2))
        self.assertAlmostEqual(self.calc.total_weight, 12 * 4.949 + 10 * self.calc.line_ids[1].mass_one, places=0)
        # перетащить, копия, удалить
        rows = self.calc.zk_move_row(data["rows"][0]["id"], data["rows"][1]["id"], True)["rows"]
        self.assertEqual(rows[1]["name"], "МН 201-5")
        rows = self.calc.zk_duplicate_row(rows[1]["id"])["rows"]
        self.assertEqual([r["name"] for r in rows[:3]], ["МН 104-1 L2400", "МН 201-5", "МН 201-5"])
        rows = self.calc.zk_delete_row(rows[2]["id"])["rows"]
        self.assertEqual(len(rows), 4)

    def test_metal_xlsx_and_menu(self):
        self._type(self.calc.zk_rows()["rows"][0]["id"], "мн 201-5 12шт")
        data = self.calc._zk_metal_xlsx()
        self.assertEqual(data[:2], b"PK")
        items, metal = self.calc._zk_metal_rows()
        self.assertAlmostEqual(sum(m[3] for m in metal), items[0][6], places=6)
        menu = self.calc.pmk_doc_menu()
        self.assertEqual([i["key"] for i in menu["print"]], ["pdf", "dxf", "xlsx"])
        self.assertEqual([i["key"] for i in menu["create"]], ["laser"])

    def test_drawing_queue(self):
        """«Подготовить чертежи» → задание в папке очереди; ответ процесса (подменён файлами) —
        чертежи в строках; строку поменяли за время рисования — её чертёж не берём."""
        rows = self._type(self.calc.zk_rows()["rows"][0]["id"], "мн 201-5 12шт")["rows"]
        self.calc.zk_save_row(False, {"after_id": rows[0]["id"], "name": "м1-9-7 4шт"})
        l1, l2 = self.calc.line_ids.sorted("sequence")
        tmp = self.env["ir.attachment"]._filestore()  # папка, куда можно писать
        with patch.dict(os.environ, {"PMK_ZK_QUEUE": os.path.join(tmp, "zk_test_queue")}):
            self.calc.action_zk_draw()
            job = self.calc.job_ids
            self.assertEqual(job.state, "running")
            self.assertTrue(os.path.exists(os.path.join(job.workdir, "queued")))
            with open(os.path.join(job.workdir, "input.json"), encoding="utf-8") as f:
                inp = json.load(f)
            self.assertEqual([i["mark"] for i in inp["items"]], ["МН 201-5", "М1-9-7"])
            self.assertEqual((l1.draw_state, self.calc.draw_busy), ("queued", True))
            # процесс нарисовал; вторую строку тем временем поменяли
            l2.mark = "М1-9-6"
            os.makedirs(os.path.join(job.workdir, "out"))
            for name in ("a.pdf", "a.png"):
                with open(os.path.join(job.workdir, "out", name), "wb") as f:
                    f.write(b"%PDF-1.4 test" if name.endswith("pdf") else b"\x89PNG")
            result = {"items": [{"key": str(l1.id), "for_key": inp["items"][0]["for_key"], "pdf": "out/a.pdf",
                                 "png": "out/a.png"},
                                {"key": str(l2.id), "for_key": inp["items"][1]["for_key"], "pdf": "out/a.pdf"}]}
            with open(os.path.join(job.workdir, "result.json"), "w", encoding="utf-8") as f:
                json.dump(result, f)
            workdir = job.workdir
            self.env["pmk.zk.job"]._cron_collect()
            self.assertEqual(job.state, "done")
            self.assertFalse(os.path.exists(workdir), "папка задания убрана")
            self.assertEqual(l1.draw_state, "done")
            self.assertEqual(base64.b64decode(l1.pdf), b"%PDF-1.4 test")
            self.assertEqual(l2.draw_state, "error")
            self.assertIn("изменили", l2.draw_error)
            # поменяли марку — чертёж устарел
            l1.mark = "МН 201-6"
            self.assertEqual(l1.draw_state, "stale")

    def test_worker_missing(self):
        """Процесса нет дольше 2 мин — задание ошибкой с причиной, строки не висят «в очереди»."""
        self._type(self.calc.zk_rows()["rows"][0]["id"], "мн 201-5 12шт")
        tmp = self.env["ir.attachment"]._filestore()
        with patch.dict(os.environ, {"PMK_ZK_QUEUE": os.path.join(tmp, "zk_test_queue2")}):
            self.calc.action_zk_draw()
            job = self.calc.job_ids
            job.started_at = "2026-01-01 00:00:00"
            self.env["pmk.zk.job"]._cron_collect()
            self.assertEqual(job.state, "error")
            self.assertIn("не отвечает", job.error)
            self.assertEqual(self.calc.line_ids.draw_state, "error")

    def test_laser_task(self):
        rows = self._type(self.calc.zk_rows()["rows"][0]["id"], "мн 201-5 12шт")["rows"]
        self.calc.zk_save_row(False, {"after_id": rows[0]["id"], "name": "мн 101-1 2шт"})
        action = self.calc.action_zk_laser_task()
        task = self.env["pmk.laser.task"].browse(action["res_id"])
        self.assertEqual(self.calc.laser_task_id, task)
        parts = {(p.name, p.thickness_mm, p.qty) for p in task.part_ids}
        self.assertEqual(parts, {("МН 201-5 поз.1 пластина", 10.0, 12), ("МН 201-5 поз.2 пластина отв", 10.0, 12),
                                 ("МН 101-1 поз.1 пластина", 6.0, 2)})
        self.assertTrue(all(p.drawing for p in task.part_ids))
        again = self.calc.action_zk_laser_task()
        self.assertEqual(again["res_id"], task.id, "второе задание не заводим — открываем первое")
