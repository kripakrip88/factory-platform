# -*- coding: utf-8 -*-
"""Задача 317: подключение к боту по личной ссылке и заявки «Хотят подключиться» — без сети."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

from .test_bot import FakeApi

ADMIN_TG = "3578814"
STRANGER = 777001


@tagged("post_install", "-at_install")
class TestTelegramJoin(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.users"].sudo().search([("pmk_telegram_id", "=", ADMIN_TG)]).write({"pmk_telegram_id": False})
        cls.admin = new_test_user(cls.env, login="tg_join_admin", name="Админ Тест",
                                  groups="base.group_system")
        cls.admin.pmk_telegram_id = ADMIN_TG
        cls.igor = new_test_user(cls.env, login="tg_join_igor", name="Игорь Бутов Тест",
                                 groups="base.group_user")
        cls.env["ir.config_parameter"].sudo().set_param("web.base.url", "https://erppark.ru")

    def setUp(self):
        super().setUp()
        self.api = FakeApi()
        patcher = patch.object(type(self.env["pmk.telegram.bot"]), "_pmk_api", lambda _self: self.api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bot = self.env["pmk.telegram.bot"].sudo()

    def _msg(self, text, tg_id=STRANGER, first="Игорь", last="Бутов", username="igor_b"):
        self.bot.pmk_handle_update({"message": {
            "message_id": 1, "chat": {"id": tg_id, "type": "private"},
            "from": {"id": tg_id, "first_name": first, "last_name": last, "username": username},
            "text": text}})

    def _to(self, chat):
        return [m for m in self.api.sent if str(m[0]) == str(chat)]

    def test_stranger_request_and_admin_notified_once(self):
        self._msg("/start")
        self._msg("/start")
        join = self.env["pmk.telegram.join"].search([("tg_id", "=", str(STRANGER))])
        self.assertEqual((join.name, join.username, join.count, join.state), ("Игорь Бутов", "igor_b", 2, "new"))
        admin_msgs = self._to(ADMIN_TG)
        self.assertEqual(len(admin_msgs), 1, "Администратору — один раз, не на каждый /start.")
        self.assertIn("хочет подключиться", admin_msgs[0][1])
        url = admin_msgs[0][2]["inline_keyboard"][0][0]["url"]
        self.assertIn("/odoo/action-pmk_telegram.action_pmk_telegram_join/%d" % join.id, url)
        self.assertIn("Заявка отправлена", self._to(STRANGER)[-1][1])

    def test_admin_links_request(self):
        self._msg("/start")
        join = self.env["pmk.telegram.join"].search([("tg_id", "=", str(STRANGER))])
        wizard = self.env["pmk.telegram.join.link"].with_context(default_join_id=join.id).create({})
        self.assertEqual(wizard.user_id, self.igor, "Похожий по имени — подставлен.")
        wizard.action_link()
        self.assertEqual(self.igor.pmk_telegram_id, str(STRANGER))
        self.assertEqual((join.state, join.user_id), ("linked", self.igor))
        last = self._to(STRANGER)[-1]
        self.assertIn("Готово, доступ есть", last[1])
        self.assertTrue(last[2]["keyboard"], "Меню — сразу.")

    def test_personal_link(self):
        action = self.igor.with_user(self.igor).action_pmk_telegram_link()
        show = self.env["pmk.telegram.link.show"].browse(action["res_id"])
        self.assertTrue(show.is_self)
        token = show.link.split("start=")[1]
        self.assertTrue(show.link.startswith("https://t.me/Dv_laba_bot?start="))
        self.assertLessEqual(len(token), 64)
        self._msg("/start " + token, tg_id=777002)
        self.assertEqual(self.igor.pmk_telegram_id, "777002")
        self.assertFalse(self.igor.sudo().pmk_telegram_link_hash, "Ссылка разовая.")
        self.assertIn("Готово, доступ есть", self._to(777002)[-1][1])
        self.assertFalse(self._to(ADMIN_TG), "По ссылке администратора не беспокоим.")
        self.assertFalse(self.env["pmk.telegram.join"].search([("tg_id", "=", "777002")]))

    def test_expired_link_becomes_request(self):
        action = self.igor.with_user(self.igor).action_pmk_telegram_link()
        token = self.env["pmk.telegram.link.show"].browse(action["res_id"]).link.split("start=")[1]
        self.igor.sudo().pmk_telegram_link_until = fields.Datetime.now() - timedelta(minutes=1)
        self._msg("/start " + token, tg_id=777003)
        self.assertFalse(self.igor.pmk_telegram_id)
        self.assertIn("устарела", self._to(777003)[-1][1])
        self.assertTrue(self.env["pmk.telegram.join"].search([("tg_id", "=", "777003")]))

    def test_only_self_or_admin_gets_link(self):
        other = new_test_user(self.env, login="tg_join_other", groups="base.group_user")
        with self.assertRaises(AccessError):
            self.igor.with_user(other).action_pmk_telegram_link()
        self.assertTrue(self.igor.with_user(self.admin).action_pmk_telegram_link())

    def test_ignored_gets_no_access(self):
        self._msg("/start")
        join = self.env["pmk.telegram.join"].search([("tg_id", "=", str(STRANGER))])
        join.action_pmk_ignore()
        self._msg("/start")
        self.assertEqual(self._to(STRANGER)[-1][1], "Нет доступа.")
        self.assertEqual(len(self._to(ADMIN_TG)), 1)
