# -*- coding: utf-8 -*-
"""Раскрой листа в задании лазеру: вход по контракту, процесс, сводка, очередь.

Пока движка в lib/ нет, процесс — заглушка stub/stub_job.py тем же runner.py и в том
же окружении, что боевой запуск (только ждём его на месте). Когда приедет пакет
sheet_nest, те же тесты погоняют его: проверки здесь — контракта и экрана, а не чисел.
"""
import base64
import json
import os
import sys
from unittest import mock

from lxml import etree

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..models.run import LIB_DIR

STUB = not os.path.isdir(os.path.join(LIB_DIR, "sheet_nest"))


def _dxf(w=120, h=40, hole=8):
    """Пластина w×h с отверстием — тем же писателем DXF, что тесты движка (lib/tests/fixtures)."""
    sys.path.insert(0, os.path.join(LIB_DIR, "tests", "fixtures"))
    try:
        from dxf_writer import DxfDoc
    finally:
        sys.path.pop(0)
    doc = DxfDoc()
    doc.entities.lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], closed=True)
    if hole:
        doc.entities.circle((w / 2, h / 2), hole)
    return doc.dxf_bytes()


DXF = _dxf()


@tagged("post_install", "-at_install")
class TestSheetNest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True,
                                       mail_create_nolog=True, mail_create_nosubscribe=True))
        Sheet = cls.env["pmk.metal.sheet"]
        cls.sheet = Sheet.search([("thickness_mm", "=", 1.5)], limit=1) or Sheet.create({
            "sheet_type": "Оцинкованный", "thickness_mm": 1.5, "gost": "ГОСТ 14918-2020",
            "mass_per_sqm": 11.775})
        cls.machine = cls.env["pmk.laser.machine"].create({
            "name": "Станок-проба раскроя", "max_width_mm": 1500, "max_length_mm": 6000})

    def _job(self, parts=(("Решётка", 30),), **vals):
        job = self.env["pmk.laser.job"].create(dict({
            "machine_id": self.machine.id, "sheet_id": self.sheet.id, "note": "Проба"}, **vals))
        for name, qty in parts:
            self.env["pmk.laser.job.part"].create({
                "job_id": job.id, "name": name, "qty": qty,
                "drawing": base64.b64encode(DXF), "drawing_name": name + ".dxf"})
        return job

    def _run(self, job, kind="plan", strategy=None):
        """То же, что кнопка, но процесс ждём здесь (sync)."""
        run = self.env["pmk.sheet.nest.run"].create({
            "laser_job_id": job.id, "kind": kind, "strategy": strategy,
            "params_json": json.dumps(job._nest_params()), "fingerprint": job._nest_fingerprint()})
        run._launch(sync=True)
        job.invalidate_recordset()
        return run

    # ------------------------------------------------------------ вход
    def test_input_by_contract(self):
        job = self._job(parts=(("Решётка", 30), ("Косынка", 4)))
        job.part_ids[0].nest_label = "ЗК-12"
        job.nest_label_all = "ЛР"
        job.part_ids[1].nest_microjoint = True
        self.env["ir.config_parameter"].sudo().set_param("pmk_sheet_nest.font_strokes_json", '{"proba": 1}')
        run = self.env["pmk.sheet.nest.run"].create({
            "laser_job_id": job.id, "params_json": json.dumps(job._nest_params())})
        wd = os.path.join(run._workroot(), "t%d" % run.id)
        os.makedirs(os.path.join(wd, "in"), exist_ok=True)
        try:
            inp = job._nest_input(run, wd)
            self.assertEqual(inp["contract"], "sheet_nest.job/1")
            self.assertEqual(inp["run_id"], run.id)
            self.assertTrue(inp["title"].startswith("1,5мм "), "толщина первой — так читает разбор pmk_laser")
            self.assertEqual([(i["name"], i["qty"]) for i in inp["inputs"]], [("Решётка", 30), ("Косынка", 4)])
            self.assertTrue(all(os.path.exists(os.path.join(wd, i["file"])) for i in inp["inputs"]))
            self.assertEqual(inp["inputs"][0]["key"], "pmk.laser.job.part,%d" % job.part_ids[0].id)
            self.assertEqual(inp["labels"], {"Решётка": "ЗК-12", "*": "ЛР"})
            self.assertEqual(inp["microjoints"], ["Косынка"])
            self.assertEqual(inp["sheet"], {"W": 1250, "L": 2500})
            self.assertTrue(inp["compare"])
            self.assertTrue(inp["vent_nesting_lib"].endswith(os.path.join("pmk_vent_nest", "lib")))
            self.assertEqual(inp["font"], "in/font.json", "таблица шрифта — копией в папку прогона")
            with open(os.path.join(wd, "in", "font.json"), encoding="utf-8") as f:
                self.assertEqual(f.read(), '{"proba": 1}')
        finally:
            import shutil
            shutil.rmtree(wd, ignore_errors=True)

    def test_checks(self):
        job = self._job(parts=(("Решётка", 3), ("Решётка", 2)))
        with self.assertRaisesRegex(UserError, "одинаковые имена"):
            job.action_nest_plan()
        job = self._job(parts=(("Решётка", 15000), ("Косынка", 5001)))
        with self.assertRaisesRegex(UserError, "не больше 20000"):
            job.action_nest_plan()
        job = self._job()
        job.part_ids.nest_label = "ЗК-1"
        self.env["ir.config_parameter"].sudo().set_param("pmk_sheet_nest.font_strokes_json", False)
        with self.assertRaisesRegex(UserError, "Подписи пока недоступны"):
            job.action_nest_plan()
        job = self._job(parts=())
        with self.assertRaisesRegex(UserError, "Нечего раскладывать"):
            job.action_nest_plan()
        job = self._job(nest_sheet_w=2000, nest_sheet_l=6000)
        with self.assertRaisesRegex(UserError, "не помещается на стол"):
            job.action_nest_plan()
        job = self._job(sheet_id=False)
        with self.assertRaisesRegex(UserError, "Выберите лист"):
            job.action_nest_plan()

    def test_coedge_and_bridge_exclusive(self):
        job = self._job()
        job.nest_coedge = True
        with self.assertRaises(ValidationError):
            job.nest_bridge = True
            job.flush_recordset()

    # ------------------------------------------------------------ путь
    def test_plan_pick_build(self):
        job = self._job()
        self.assertEqual(job.nest_status_kind, "none")
        plan = self._run(job)
        self.assertEqual(plan.state, "done", plan.error)
        self.assertEqual(job.nest_status_kind, "done", job.nest_status)
        res = json.loads(job.nest_summary_json)
        self.assertEqual([r.get("name") or r.get("strategy") for r in res["strategies"]],
                         ["short", "safe", "safe0", "hill"])
        self.assertGreater(plan.sheets, 0)
        self.assertFalse(job.nest_can_build, "порядок резки не выбран")
        job.nest_strategy = "safe"
        self.assertTrue(job.nest_can_build)
        build = self._run(job, "build", "safe")
        self.assertEqual(build.state, "done", build.error)
        if STUB:
            self.assertFalse(build.ok, "заглушка программу не собирает")
            self.assertFalse(job.nest_can_accept)
            self.assertIn("Заглушка", job.nest_warnings)
            with self.assertRaises(UserError):
                job.action_nest_accept()
        else:
            self.assertTrue(build.ok, build.result_json)
            self.assertTrue(build.lxds_name.endswith(".lxds"))
            self.assertTrue(job.nest_can_accept)
            self.assertTrue(job.with_context(bin_size=False).nest_png_order, "картинка порядка резки")
            # Программа движка — в разбор pmk_laser как есть: листы в очередь, детали с чертежами.
            job.action_nest_accept()
            self.assertEqual(job.file_name, build.lxds_name)
            self.assertEqual(len(job.sheet_ids), build.sheets)
            self.assertEqual(job.part_ids.filtered(lambda p: p.name == "Решётка").qty, 30)
            self.assertTrue(job.part_ids.filtered(lambda p: p.name == "Решётка").drawing, "чертёж сохранился")
        notes = job.message_ids.mapped("body")
        self.assertTrue(any("Раскрой готов" in (b or "") for b in notes), "заметка о раскрое в истории")

    def test_stale_after_change(self):
        job = self._job()
        self._run(job)
        job.nest_strategy = "short"
        self.assertTrue(job.nest_can_build)
        job.part_ids[0].qty = 31
        job.invalidate_recordset()
        self.assertEqual(job.nest_status_kind, "stale")
        self.assertFalse(job.nest_can_build)
        with self.assertRaisesRegex(UserError, "пересчитайте"):
            job.action_nest_build()

    def test_bad_dxf_is_user_error(self):
        job = self._job()
        job.part_ids[0].drawing = base64.b64encode(b"not a drawing")
        run = self._run(job)
        self.assertEqual(run.state, "error")
        self.assertTrue(run.error_user, run.error)
        self.assertEqual(job.nest_status_kind, "error")

    def test_accept_puts_program_into_job(self):
        job = self._job()
        self._run(job)
        job.nest_strategy = "safe"
        build = self.env["pmk.sheet.nest.run"].create({
            "laser_job_id": job.id, "kind": "build", "strategy": "safe", "state": "done", "ok": True,
            "fingerprint": job._nest_fingerprint(), "lxds": base64.b64encode(b"PK-proba"),
            "lxds_name": "1,5мм проба.lxds", "sheets": 3, "result_json": "{}"})
        job.invalidate_recordset()
        self.assertTrue(job.nest_can_accept)
        self.assertEqual(job.nest_program, "1,5мм проба.lxds ✓")
        with mock.patch.object(type(job), "action_parse_file", autospec=True, return_value=True) as parse:
            job.action_nest_accept()
        parse.assert_called_once()
        self.assertEqual(job.file_name, "1,5мм проба.lxds")
        self.assertEqual(base64.b64decode(job.with_context(bin_size=False).file), b"PK-proba")
        self.assertTrue(build.ok)

    def test_part_fields_survive_reparse(self):
        job = self._job()
        job.part_ids.write({"nest_label": "ЗК-1", "nest_microjoint": True})
        layout = type("L", (), {"parts": [type("P", (), {"name": "Решётка", "amount": 30, "amount_used": 30})]})
        commands = job._part_commands(layout)
        created = [c[2] for c in commands if c[0] == 0]
        self.assertEqual(created[0]["nest_label"], "ЗК-1")
        self.assertTrue(created[0]["nest_microjoint"])
        self.assertTrue(created[0]["drawing"], "чертёж переносит pmk_laser")

    # ------------------------------------------------------------ очередь
    def test_queue_shared_with_vent(self):
        job = self._job()
        busy = self.env["pmk.sheet.nest.run"].create({"laser_job_id": job.id, "state": "running"})
        second = self._job(parts=(("Косынка", 4),))
        second.action_nest_plan()
        run = second.nest_run_ids
        self.assertEqual(run.state, "queued", "пока считается другой раскрой — ждать")
        vent = self.env["pmk.vent.nest.job"]
        # Исходный _launch пакета вентзонтов — следующий за нашим в цепочке наследования.
        base = [c for c in type(vent).__mro__ if "_launch" in c.__dict__][1]
        with mock.patch.object(base, "_launch", autospec=True) as base_launch:
            vent.browse()._launch()
        base_launch.assert_not_called()
        busy.state = "error"
        with mock.patch.object(type(run), "_launch", autospec=True) as launch:
            self.env["pmk.sheet.nest.run"]._cron_collect()
        launch.assert_called_once()

    def test_tab_after_parts(self):
        views = self.env["pmk.laser.job"].get_views([(False, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        names = [p.get("name") for p in arch.xpath("//notebook/page")]
        self.assertIn("sheet_nest", names)
        self.assertEqual(names[names.index("parts") + 1], "sheet_nest")
        self.assertTrue(arch.xpath("//field[@name='nest_strategy'][@widget='pmk_sheet_nest_strategy']"))

    def test_nest_document_plan_all(self):
        """Раскрой-документ: «Рассчитать все» — прогон на каждую программу по толщине."""
        Sheet = self.env["pmk.metal.sheet"]
        if not Sheet.search([("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", 3)], limit=1):
            Sheet.create({"sheet_type": "Гладкий", "thickness_mm": 3, "gost": "ГОСТ", "mass_per_sqm": 23.55})
        if not Sheet.search([("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", 1.5)], limit=1):
            Sheet.create({"sheet_type": "Гладкий", "thickness_mm": 1.5, "gost": "ГОСТ", "mass_per_sqm": 11.78})
        task = self.env["pmk.laser.task"].create({"note": "проба"})
        for name, t in (("пл1", 1.5), ("пл2", 3)):
            self.env["pmk.laser.task.part"].create({"task_id": task.id, "name": name, "thickness_mm": t,
                                                    "qty": 4, "drawing": base64.b64encode(DXF)})
        nest = self.env["pmk.laser.nest"].browse(task.action_nest_all()["res_id"])
        self.assertEqual(len(nest.program_ids), 2)
        with mock.patch.object(type(self.env["pmk.sheet.nest.run"]), "_start", autospec=True) as start:
            nest.action_nest_plan_all()
        self.assertEqual(start.call_count, 2)
        self.assertEqual(len(nest.program_ids.nest_run_ids), 2)
        view = self.env["pmk.laser.nest"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn('widget="pmk_sheet_nest_programs"', view)

