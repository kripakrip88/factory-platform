# -*- coding: utf-8 -*-
"""Лазер: «Посмотреть» чертёж детали окном DXF — разбор UX, шаг 46.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py):
    odoo -d laser_test -i pmk_laser,pmk_drawing --test-enable \\
         --test-tags /pmk_laser:TestLaserDrawingView --stop-after-init

Что ловим: кнопка в строке детали есть и видна только с чертежом; действие
открывает окно pmk_drawing на вложении поля «Чертёж» (а не на чужом
файле) и скачивает под именем чертежа; без модуля — всплывающее
«недоступен», а не ошибка; сотрудник лазера видит чертёж своей детали.
"""
import base64
from unittest import mock

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

# Минимальный DXF R12: одна линия на слое «КОНТУР».
DXF = '\n'.join([
    '  0', 'SECTION', '  2', 'ENTITIES',
    '  0', 'LINE', '  8', 'КОНТУР',
    ' 10', '0.0', ' 20', '0.0', ' 30', '0.0',
    ' 11', '120.0', ' 21', '40.0', ' 31', '0.0',
    '  0', 'ENDSEC', '  0', 'EOF', '',
]).encode('cp1251')


@tagged("post_install", "-at_install")
class TestLaserDrawingView(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # pmk_drawing читает кэш чертежей отдельной транзакцией — в режиме
        # теста она обёртка над курсором теста.
        cls.registry_enter_test_mode_cls()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True,
                                       mail_create_nolog=True, mail_create_nosubscribe=True))
        machine = cls.env["pmk.laser.machine"].create({"name": "Станок-проба 46", "power_kw": 4.6})
        cls.job = cls.env["pmk.laser.job"].create({"machine_id": machine.id})
        cls.part = cls.env["pmk.laser.job.part"].create({
            "job_id": cls.job.id, "name": "Кронштейн", "qty": 4,
            "drawing": base64.b64encode(DXF), "drawing_name": "Кронштейн К-1.dxf",
        })
        cls.bare = cls.env["pmk.laser.job.part"].create({
            "job_id": cls.job.id, "name": "Без чертежа", "qty": 1})

    def test_button_in_part_row(self):
        views = self.env["pmk.laser.job"].get_views(
            [(self.env.ref("pmk_laser.view_laser_job_form").id, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        buttons = arch.xpath("//field[@name='part_ids']/list/button[@name='action_view_drawing']")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get("invisible"), "not drawing")
        self.assertEqual(buttons[0].get("string"), "Посмотреть")

    def test_action_opens_field_attachment(self):
        attachment = self.env["ir.attachment"].search([
            ("res_model", "=", "pmk.laser.job.part"), ("res_id", "=", self.part.id),
            ("res_field", "=", "drawing")])
        self.assertEqual(len(attachment), 1)
        with mock.patch.object(type(self.part), "_pmk_drawing_ready", return_value=True):
            action = self.part.action_view_drawing()
        self.assertEqual((action["type"], action["tag"]), ("ir.actions.client", "pmk_drawing.view"))
        params = action["params"]
        self.assertEqual(params["attachment_id"], attachment.id)
        self.assertEqual(params["name"], "Кронштейн К-1.dxf")
        self.assertIn("filename_field=drawing_name", params["download_url"])

    def test_without_drawing_module(self):
        with mock.patch.object(type(self.part), "_pmk_drawing_ready", return_value=False):
            action = self.part.action_view_drawing()
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["type"], "warning")

    def test_no_drawing(self):
        with self.assertRaises(UserError):
            self.bare.action_view_drawing()

    def test_laser_user_sees_drawing(self):
        if "pmk.drawing" not in self.env:
            self.skipTest("нет модуля pmk_drawing")
        drawing = self.env["pmk.drawing"]
        if not drawing._available():
            self.skipTest("нет ezdxf")
        action = self.part.action_view_drawing()
        # Детали лазера читает любой сотрудник (ir.model.access pmk_laser) —
        # и чертёж детали, приложенный к её полю «Чертёж».
        user = new_test_user(self.env, login="laser46", groups="base.group_user")
        with mock.patch.object(type(drawing), "_run_renderer", autospec=True,
                               return_value={"ok": True, "items": [], "cache": False}):
            payload = drawing.with_user(user).attachment_preview(action["params"]["attachment_id"])
        self.assertTrue(payload["ok"], payload.get("reason"))
