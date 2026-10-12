# -*- coding: utf-8 -*-
"""Раскрой вентзонтов: вход, запуск отдельного процесса, результат, программы.

Сквозной тест гоняет настоящий пакет раскроя тем же runner.py и в том же окружении,
что и боевой запуск (только ждёт процесс на месте). Он же ловит ошибку часового пояса
пакета 1.0.0 (в контейнере в UTC все программы выходили «не выдавать»).
"""
import json
import os
import tempfile

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestVentNest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        html = str(order.nest_html)
        self.assertIn("Свес, мм", html)
        self.assertIn("0,65 мм", html, "толщина не округляется до 0,7")
        self.assertIn("125", html)
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
        self.assertIn("бухта", att.name)

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
