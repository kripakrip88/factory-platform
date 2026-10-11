# -*- coding: utf-8 -*-
"""Вентзонты: перенос генератора 51/51 и обвязка Odoo вокруг него."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_calc.tools import vent_hood as V

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.dirname(HERE)


@tagged("post_install", "-at_install")
class TestVentHood(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Sheet = cls.env["pmk.metal.sheet"]
        cls.sheet = Sheet.search([("sheet_type", "=", "Оцинкованный"),
                                  ("thickness_mm", "=", 0.5)], limit=1)
        if not cls.sheet:
            cls.sheet = Sheet.create({"name": "Оцинк. 0,5 (тест вентзонта)",
                                      "sheet_type": "Оцинкованный", "thickness_mm": 0.5})
        cls.ral = cls.env.ref("pmk_calc.coating_ral8017")
        cls.zinc = cls.env.ref("pmk_calc.coating_zinc")

    def _hood(self, **vals):
        data = {"width": 750, "length": 4000, "sheet_id": self.sheet.id}
        data.update(vals)
        return self.env["pmk.vent.hood"].create(data)

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

    def test_spec_is_generator_answer(self):
        hood = self._hood(coating_id=self.ral.id)
        expected = V.spec(V.hood(750, 4000), 0.5, "8017")
        self.assertEqual(json.loads(hood.spec_json), json.loads(json.dumps(expected, ensure_ascii=False)))
        self.assertEqual(hood.name[:3], "ВЗ-")
        self.assertEqual(hood.hood_label, "вш 750х4000")
        self.assertEqual(hood.lapki, 28)
        self.assertEqual(hood.klepki, 24)
        self.assertEqual(hood.material_name,
                         "Лист оцинкованный с полимерным покрытием RAL 8017 0.5 мм")
        self.assertIn("окрашенный лист", hood.warnings_text)
        self.assertEqual(hood.subtitle, "вш 750х4000 · " + hood.material_name)
        self.assertIn("Крышка торцевая", hood.spec_html)

    def test_zinc_and_totals(self):
        hood = self._hood(coating_id=self.zinc.id, qty=3)
        self.assertEqual(hood.material_name, "Лист оцинкованный 0.5 мм")
        self.assertNotIn("окрашенный", hood.warnings_text or "", "Цинк не переворачивать можно.")
        self.assertIn("по правилу", hood.warnings_text, "На 750 шаблона нет — генератор так и пишет.")
        self.assertAlmostEqual(hood.total_mass_net_kg, hood.mass_net_kg * 3, places=3)
        self.assertAlmostEqual(hood.total_sheet_1250_m, hood.sheet_1250_m * 3, places=3)
        self.assertEqual(hood.coating_id, self.zinc, "Без выбора — цинк, как у доборки.")
        self.assertEqual(self.env["pmk.vent.hood"].create({}).coating_id, self.zinc)

    def test_width_over_length_is_error_not_drawing(self):
        hood = self._hood(width=1200, length=900)
        self.assertIn("поменяйте местами", hood.spec_error)
        self.assertFalse(hood.spec_json)
        with self.assertRaises(UserError):
            hood.action_download_dxf()

    def test_outside_tested_range_warns(self):
        hood = self._hood(width=1500, length=2000)
        self.assertIn("вне проверенного ряда", hood.warnings_text)

    def test_dxf_download(self):
        hood = self._hood(coating_id=self.ral.id)
        action = hood.action_download_dxf()
        hood.action_download_dxf()
        att = self.env["ir.attachment"].search([("res_model", "=", "pmk.vent.hood"),
                                                ("res_id", "=", hood.id)])
        self.assertEqual(len(att), 1, "Повторное скачивание не плодит копии.")
        self.assertEqual(att.name, "vsh_750x4000_t0.5_RAL8017.dxf")
        self.assertEqual(att.raw.decode("utf-8"), V.to_dxf(V.hood(750, 4000)))
        self.assertIn("/web/content/", action["url"])

    def test_change_size_recomputes(self):
        hood = self._hood()
        before = hood.klepki
        hood.write({"width": 1250, "length": 1600})
        self.assertEqual(hood.hood_label, "вш 1250х1600")
        self.assertNotEqual(hood.klepki, before)

    def test_sheet_list_is_galvanized_only(self):
        field = self.env["pmk.vent.hood"]._fields["sheet_id"]
        self.assertEqual(field.domain, [("sheet_type", "=", "Оцинкованный")])
        self.assertEqual(self.env["pmk.dobor.order.line"]._fields["sheet_id"].domain, field.domain,
                         "Список металла — тот же, что у доборки.")

    def test_form_opens_for_employee(self):
        user = self.env["res.users"].create({
            "name": "Сотрудник ВЗ", "login": "vh_employee",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        views = self.env["pmk.vent.hood"].with_user(user).get_views([(False, "form"), (False, "list")])
        self.assertIn("action_download_dxf", views["views"]["form"]["arch"])
        hood = self.env["pmk.vent.hood"].with_user(user).create(
            {"width": 600, "length": 2400, "sheet_id": self.sheet.id})
        self.assertTrue(hood.spec_json)
