# -*- coding: utf-8 -*-
"""Раскрой вентзонтов: вход, запуск отдельного процесса, результат, программы.

Сквозной тест гоняет настоящий пакет раскроя тем же runner.py и в том же окружении,
что и боевой запуск (только ждёт процесс на месте). Он же ловит ошибку часового пояса
пакета 1.0.0 (в контейнере в UTC все программы выходили «не выдавать»).
"""
import importlib.util
import json
import os
import tempfile
import time
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestVentNest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._data()

    @classmethod
    def _data(cls):
        Sheet = cls.env["pmk.metal.sheet"]
        cls.sheet065 = Sheet.search([("sheet_type", "=", "Оцинкованный"), ("thickness_mm", "=", 0.65)],
                                    limit=1) or Sheet.create({
            "sheet_type": "Оцинкованный", "thickness_mm": 0.65, "gost": "ГОСТ 14918-2020",
            "mass_per_sqm": 5.1025})
        cls.ral = cls.env.ref("pmk_calc.coating_ral8017")

    def _order(self, *sizes):
        lines = [(0, 0, dict({"coating_id": self.ral.id, "sheet_id": self.sheet065.id}, **s)) for s in sizes]
        return self.env["pmk.vent.hood.order"].create({"line_ids": lines})

    def _job(self, order, kind="plan", builds=None):
        return self.env["pmk.vent.nest.job"].create({
            "order_id": order.id, "kind": kind, "gap": order.nest_gap, "edge": order.nest_edge,
            "fingerprint": order._nest_fingerprint(), "builds_json": json.dumps(builds or [])})

    def test_same_hood_twice_is_one_dxf(self):
        order = self._order({"width": 500, "length": 1000, "qty": 2}, {"width": 500, "length": 1000, "qty": 3})
        dxf, qty, inp = self._job(order)._input()
        self.assertEqual(len(dxf), 1, "пакет не принимает один зонт дважды — строки складываются")
        self.assertEqual(list(qty.values()), [5])
        self.assertEqual(inp["dxf"], list(dxf))

    def test_params_checked(self):
        order = self._order({"width": 500, "length": 1000})
        order.nest_gap = 0.1
        with self.assertRaises(UserError):
            order.action_nest_plan()
        order.nest_gap, order.nest_edge = 2, 101
        with self.assertRaises(UserError):
            order.action_nest_plan()

    def test_plan_then_build(self):
        order = self._order({"width": 500, "length": 1000, "qty": 2})
        self.assertEqual(order.nest_status_kind, "none")
        plan = self._job(order)
        plan._launch(sync=True)
        self.assertEqual(plan.state, "done", plan.error)
        self.assertTrue(plan.png, "картинка раскроя")
        self.assertFalse(os.path.exists(plan.workdir), "папка задания убрана")
        mat = order.nest_material_ids
        self.assertEqual(len(mat), 1)
        self.assertEqual(mat.key, "ral8017|0.65")
        self.assertGreater(mat.stock_kg, 0)
        self.assertGreater(mat.coil_kg, 0)
        sves = {(int(r["sves"]), r["source"]) for r in json.loads(mat.sves_json)}
        self.assertEqual(sves, {(s, src) for s in (150, 145, 140, 135, 130, 125) for src in ("stock", "coil")})
        self.assertEqual(mat.price_sheet, self.sheet065.display_name)
        self.assertEqual(order.nest_status_kind, "done")
        self.assertIn("Раскрой готов", order.message_ids[0].body)

        mat.write({"choice": "coil", "sves": "150"})
        build = self._job(order, "build", [{"key": mat.key, "source": "coil", "sves": 150, "label": "t"}])
        build._launch(sync=True)
        self.assertEqual(build.state, "done", build.error)
        res = json.loads(build.result_json)
        self.assertFalse(res["rejected"], "программа прошла самопроверку (в т.ч. пояс контейнера UTC)")
        att = self.env["ir.attachment"].search([("res_model", "=", order._name), ("res_id", "=", order.id),
                                                ("name", "like", ".lxds")])
        self.assertEqual(len(att), 1)
        self.assertRegex(att.name, r"_RAL8017_0\.65_бухта_\d\d\.\d\d\.\d\d_\d\d-\d\d\.lxds$",
                         "дата и время сборки в имени")
        # Пересборка того же материала — прежняя программа заменяется.
        build2 = self._job(order, "build", [{"key": mat.key, "source": "stock", "sves": 150, "label": "t"}])
        build2._launch(sync=True)
        self.assertEqual(build2.state, "done", build2.error)
        att = self.env["ir.attachment"].search([("res_model", "=", order._name), ("res_id", "=", order.id),
                                                ("name", "like", ".lxds")])
        self.assertEqual(len(att), 1, "одна действующая программа на материал")
        self.assertIn("склад", att.name)

        order.line_ids.qty = 3
        self.assertEqual(order.nest_status_kind, "stale")
        with self.assertRaises(UserError):
            order.action_nest_build()

    def test_dead_process_is_error(self):
        order = self._order({"width": 500, "length": 1000})
        job = self._job(order)
        wd = tempfile.mkdtemp()
        with open(os.path.join(wd, "pid"), "w") as f:
            f.write("999999")
        job.write({"state": "running", "workdir": wd, "started_at": "2026-10-12 00:00:00"})
        job._poll()
        self.assertEqual(job.state, "error")
        self.assertIn("прервался", job.error)
        self.assertEqual(order.nest_status_kind, "error")

    def test_rejected_program_not_attached(self):
        order = self._order({"width": 500, "length": 1000})
        job = self._job(order, "build")
        job.workdir = tempfile.mkdtemp()
        order._nest_apply_build(job, {"files": [{"ok": False, "filename": "x.lxds", "path": "files/0.lxds"}]})
        self.assertFalse(self.env["ir.attachment"].search([("res_model", "=", order._name),
                                                           ("res_id", "=", order.id)]))
        self.assertEqual(json.loads(job.result_json)["rejected"], ["x.lxds"])

    def test_queue_one_at_a_time(self):
        a = self._order({"width": 500, "length": 1000})
        b = self._order({"width": 500, "length": 1000})
        ja, jb = self._job(a), self._job(b)
        ja.write({"state": "running", "workdir": tempfile.mkdtemp(), "started_at": "2099-01-01 00:00:00"})
        self.env["pmk.vent.nest.job"]._cron_collect()
        self.assertEqual(jb.state, "queued", "пока считается другой заказ — ждёт")

    def test_decision_applies_sves_to_order(self):
        """«Принять решение»: свес материала — в строки заказа; ведомость/габарит — по нему."""
        order = self._order({"width": 500, "length": 1000, "qty": 2})
        before = order.line_ids.hood_size
        rows = [{"sves": sv, "source": src, "kg": 10.0, "lengths": "2500"}
                for sv in (150, 145, 140, 135, 130, 125) for src in ("stock", "coil")]
        plan = self._job(order)
        plan.write({"state": "done", "finished_at": "2026-10-12 00:00:00"})
        mat = self.env["pmk.vent.nest.material"].create({
            "order_id": order.id, "key": "ral8017|0.65", "color": "RAL 8017", "thickness": 0.65,
            "stock_kg": 10, "coil_kg": 10, "choice": "coil", "sves": "135", "sves_json": json.dumps(rows)})
        self.assertEqual(mat._lines(), order.line_ids, "ключ материала строки = ключ пакета")
        # Другой заказ считается — новое задание ждёт в очереди, процесс не запускается.
        other = self._job(self._order({"width": 500, "length": 1000}))
        other.write({"state": "running", "workdir": tempfile.mkdtemp(), "started_at": "2099-01-01 00:00:00"})
        order.action_nest_build()
        self.assertEqual(order.line_ids.sves, 135)
        self.assertEqual(order.line_ids.hood_size, "1270 × 770", "габарит = шахта + 2 × 135")
        self.assertNotEqual(order.line_ids.hood_size, before)
        self.assertIn("свес 135", order.message_ids[0].body)
        build = order.nest_job_ids.filtered(lambda j: j.kind == "build")
        self.assertEqual(build.state, "queued")
        self.assertEqual(json.loads(build.builds_json)[0]["sves"], 135)
        # Вход раскроя — DXF при стандарте 150 (пакет сверяет со своим генератором).
        dxf, _qty, _inp = build._input()
        self.assertEqual(list(dxf.values())[0], order.line_ids._vh_dxf_standard())
        self.assertNotEqual(list(dxf.values())[0], order.line_ids._vh_dxf())


@tagged("post_install", "-at_install")
class TestVentNestWorker(TransactionCase):
    """Расчётчик в отдельном контейнере (16.10.2026): очередь файлами, запасной путь,
    свес 150 без повтора, раскладки параллельно."""

    # Подготовка — как у TestVentNest (наследовать класс нельзя: его тесты прошли бы дважды).
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        TestVentNest._data.__func__(cls)

    _order = TestVentNest._order
    _job = TestVentNest._job

    def _alive_file(self, age_s=0):
        root = self.env["pmk.vent.nest.job"]._queue_root()
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, ".worker_alive")
        with open(path, "w"):
            pass
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return root

    def test_parallel_same_table(self):
        """NEST_PROCS=2 — та же таблица свеса, что по очереди; строка 150 — одна на источник."""
        order = self._order({"width": 500, "length": 1000, "qty": 2})
        one = self._job(order)
        one._launch(sync=True)
        self.assertEqual(one.state, "done", one.error)
        rows_one = json.loads(one.result_json)["sves"]
        with patch.dict(os.environ, {"NEST_PROCS": "2"}):
            two = self._job(order)
            two._launch(sync=True)
        self.assertEqual(two.state, "done", two.error)
        rows_two = json.loads(two.result_json)["sves"]
        self.assertEqual(rows_one, rows_two)
        self.assertEqual(sum(1 for r in rows_two if r["sves"] == 150), 2, "склад и бухта — по разу")

    def test_worker_takes_queue(self):
        """Расчётчик жив — Odoo ставит в очередь и не запускает процесс; результат забирает как раньше."""
        root = self._alive_file()
        order = self._order({"width": 500, "length": 1000, "qty": 2})
        job = self._job(order)
        with patch.object(type(job), "_spawn", side_effect=AssertionError("в Odoo не запускать")):
            job._launch()
        self.assertTrue(os.path.exists(os.path.join(job.workdir, "queued")))
        self.assertEqual(job.progress, "в очереди расчётчика")
        spec = importlib.util.spec_from_file_location(
            "pmk_vent_worker", os.path.join(os.path.dirname(os.path.dirname(__file__)), "worker.py"))
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        workdir = worker._next(root)
        self.assertEqual(workdir, job.workdir)
        self.assertIsNone(worker._next(root), "взятое второй раз не берётся")
        worker.run_job(root, workdir, 1)
        job._poll()
        self.assertEqual(job.state, "done", job.error)
        self.assertEqual(order.nest_status_kind, "done")

    def test_worker_gone_runs_here(self):
        """В очереди, а расчётчик молчит дольше 2 минут — считаем в Odoo."""
        self._alive_file(age_s=600)
        order = self._order({"width": 500, "length": 1000})
        job = self._job(order)
        wd = tempfile.mkdtemp()
        with open(os.path.join(wd, "queued"), "w"):
            pass
        job.write({"state": "running", "workdir": wd, "started_at": "2099-01-01 00:00:00"})
        with patch.object(type(job), "_spawn") as spawn:
            job._poll()
        spawn.assert_called_once_with(wd)
        self.assertTrue(os.path.exists(os.path.join(wd, "local")))
        self.assertFalse(os.path.exists(os.path.join(wd, "queued")))

    def test_worker_silent_is_error(self):
        order = self._order({"width": 500, "length": 1000})
        job = self._job(order)
        wd = tempfile.mkdtemp()
        for name in ("claimed", "heartbeat"):
            with open(os.path.join(wd, name), "w"):
                pass
        old = time.time() - 600
        os.utime(os.path.join(wd, "heartbeat"), (old, old))
        job.write({"state": "running", "workdir": wd, "started_at": "2099-01-01 00:00:00"})
        job._poll()
        self.assertEqual(job.state, "error")
        self.assertIn("прервался", job.error)
