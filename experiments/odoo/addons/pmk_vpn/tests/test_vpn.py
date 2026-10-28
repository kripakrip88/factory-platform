# -*- coding: utf-8 -*-
"""Ключи VPN: выдача, рассылка, синхронизация, кнопки бота — без сети."""
from unittest.mock import patch

from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.pmk_telegram.tests.test_bot import FakeApi

from ..models import bot as vpn_bot
from ..models import links
from ..models.vpn_key import PARAM_AUTO, PARAM_TOKEN

SERVER = {"host": "203.0.113.5", "sni": "example.ru", "pbk": "PUBKEY", "sid": "ab12",
          "port_tcp": 443, "port_xhttp": 8443, "xhttp_path": "/p4th"}
# Не настоящие ID: на копии базы реальные уже привязаны (поле уникальное).
ADMIN_CHAT = 5550000
WORKER_CHAT = 5550001


@tagged("post_install", "-at_install")
class TestPmkVpn(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.admin = Users.create({
            "name": "Админ ВПН", "login": "vpn_admin_test",
            "group_ids": [(4, cls.env.ref("base.group_system").id)],
            "pmk_telegram_id": str(ADMIN_CHAT)})
        cls.worker = Users.create({
            "name": "Иванов Рабочий", "login": "vpn_worker_test",
            "group_ids": [(4, cls.env.ref("base.group_user").id)],
            "pmk_telegram_id": str(WORKER_CHAT)})
        cls.no_tg = Users.create({
            "name": "Без Телеграма", "login": "vpn_notg_test",
            "group_ids": [(4, cls.env.ref("base.group_user").id)]})
        cls.Key = cls.env["pmk.vpn.key"].sudo()
        cls.Key.pmk_sync({"server": SERVER})

    def setUp(self):
        super().setUp()
        self.api = FakeApi()
        patcher = patch.object(type(self.env["pmk.telegram.bot"]), "_pmk_api",
                               lambda _self: self.api)
        patcher.start()
        self.addCleanup(patcher.stop)
        # На копии базы людей с Телеграмом больше 10 — тестовый не должен
        # остаться за пределами одной пачки.
        batch = patch("odoo.addons.pmk_vpn.models.vpn_key.SEND_BATCH", 1000)
        batch.start()
        self.addCleanup(batch.stop)
        self.bot = self.env["pmk.telegram.bot"].sudo()

    def _issue(self):
        self.Key.action_pmk_issue_all()
        return self.Key.search([("user_id", "=", self.worker.id)])

    # ── ссылки ────────────────────────────────────────────────────────────

    def test_links(self):
        main = links.vless_main("U-1", SERVER, "ПМК VPN")
        self.assertTrue(main.startswith("vless://U-1@203.0.113.5:443?"))
        self.assertIn("flow=xtls-rprx-vision", main)
        self.assertIn("sni=example.ru", main)
        reserve = links.vless_reserve("U-1", SERVER, "x")
        self.assertIn(":8443?", reserve)
        self.assertIn("type=xhttp", reserve)
        self.assertIn("path=%2Fp4th", reserve)
        self.assertEqual(links.user_id_of("u42"), 42)
        self.assertIsNone(links.user_id_of("anton"))

    # ── выдача и рассылка ────────────────────────────────────────────────

    def test_issue_only_to_telegram_users(self):
        self._issue()
        users = self.Key.search([]).user_id
        self.assertIn(self.worker, users)
        self.assertNotIn(self.no_tg, users)
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param(PARAM_AUTO), "1")

    def test_no_auto_send_before_button(self):
        """После установки модуля никому ничего не уходит, пока не нажата «Разослать»."""
        self.Key._cron_pmk_send()
        self.assertFalse(self.Key.search([]))
        self.assertFalse(getattr(self.api, "photos", []))

    def test_cron_sends_two_qr_and_instruction(self):
        key = self._issue()
        self.Key._cron_pmk_send()
        photos = [p for p in self.api.photos if p[0] == str(WORKER_CHAT)]
        self.assertEqual(len(photos), 2)              # основной + запасной
        self.assertIn(key.uuid, photos[0][2])
        self.assertTrue(photos[0][1][1].startswith(b"\x89PNG"))
        texts = [t for chat, t, _m in self.api.sent if chat == str(WORKER_CHAT)]
        self.assertTrue(any("Как подключить" in t for t in texts))
        self.assertEqual(key.state, "sent")

    def test_refused_three_times_is_failed(self):
        key = self._issue()
        self.api.send_photo = lambda *a, **k: None   # Телеграм отказывает
        for _i in range(3):
            self.Key._cron_pmk_send()
        self.assertEqual(key.state, "failed")

    def test_new_user_gets_key_automatically(self):
        self._issue()
        late = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Новенький", "login": "vpn_late_test",
            "group_ids": [(4, self.env.ref("base.group_user").id)],
            "pmk_telegram_id": "5550002"})
        self.Key._cron_pmk_send()
        self.assertEqual(self.Key.search([("user_id", "=", late.id)]).state, "sent")

    # ── синхронизация ─────────────────────────────────────────────────────

    def test_sync_returns_only_working_keys(self):
        key = self._issue()
        res = self.Key.pmk_sync({"server": SERVER})
        emails = {u["email"]: u["uuid"] for u in res["users"]}
        self.assertEqual(emails[links.email_of(self.worker.id)], key.uuid)
        self.assertEqual(res["limit"], 3)
        key.access = False
        res = self.Key.pmk_sync({})
        self.assertNotIn(links.email_of(self.worker.id), {u["email"] for u in res["users"]})
        key.access = True
        self.worker.active = False                     # уволен — ключ не работает
        res = self.Key.pmk_sync({})
        self.assertNotIn(links.email_of(self.worker.id), {u["email"] for u in res["users"]})

    def test_sync_traffic_adds_up(self):
        key = self._issue()
        email = links.email_of(self.worker.id)
        self.Key.pmk_sync({"stats": {email: {"up": 1000, "down": 2 * 1024 ** 3,
                                             "ips": ["198.51.100.1"]}}})
        self.Key.pmk_sync({"stats": {email: {"up": 0, "down": 1024 ** 3, "ips": []}}})
        row = self.env["pmk.vpn.traffic"].search([("key_id", "=", key.id)])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.bytes_down, 3 * 1024 ** 3)   # больше int4 — не переполнилось
        self.assertTrue(key.last_seen)
        self.assertEqual(key.devices_now, 0)
        key.invalidate_recordset()
        self.assertIn("ГБ", key.traffic_today)

    def test_over_limit_alerts_admin_once_a_day(self):
        key = self._issue()
        email = links.email_of(self.worker.id)
        payload = {"stats": {email: {"ips": ["a", "b", "c", "d"]}}, "blocked": {email: ["d"]}}
        self.Key.pmk_sync(payload)
        self.Key.pmk_sync(payload)
        alerts = [s for s in self.api.sent if s[0] == str(ADMIN_CHAT) and "VPN" in s[1]]
        self.assertEqual(len(alerts), 1)
        self.assertIn("Иванов Рабочий", alerts[0][1])
        self.assertEqual(key.blocked_ips, "d")

    def test_server_param_written_only_on_change(self):
        icp = self.env["ir.config_parameter"].sudo()
        with patch.object(type(icp), "set_param") as setp:
            self.Key.pmk_sync({"server": SERVER})
        setp.assert_not_called()

    # ── бот ───────────────────────────────────────────────────────────────

    def _msg(self, chat, text):
        self.bot.pmk_handle_update({"message": {
            "message_id": 1, "chat": {"id": chat, "type": "private"},
            "from": {"id": chat}, "text": text}})

    def test_bot_button_resends_key(self):
        self._issue()
        self._msg(WORKER_CHAT, "/start")
        labels = [row[0]["text"] for row in self.api.sent[-1][2]["keyboard"]]
        self.assertIn(vpn_bot.BTN_VPN, labels)
        self.assertNotIn(vpn_bot.BTN_VPN_ADMIN, labels)
        self._msg(WORKER_CHAT, vpn_bot.BTN_VPN)
        self.assertEqual(len([p for p in self.api.photos if p[0] == str(WORKER_CHAT)]), 2)

    def test_bot_no_button_before_issue(self):
        self._msg(WORKER_CHAT, "/start")
        labels = [row[0]["text"] for row in self.api.sent[-1][2]["keyboard"]]
        self.assertNotIn(vpn_bot.BTN_VPN, labels)

    def test_admin_switches_key_off(self):
        key = self._issue()
        self._msg(ADMIN_CHAT, vpn_bot.BTN_VPN_ADMIN)
        self.assertIn("Иванов Рабочий", self.api.sent[-1][1])
        self.bot.pmk_handle_update({"callback_query": {
            "id": "cb", "data": "vpn:off:%d" % key.id, "from": {"id": ADMIN_CHAT},
            "message": {"message_id": 7, "chat": {"id": ADMIN_CHAT},
                        "text": "VPN: сотрудники (сегодня / месяц)"}}})
        self.assertFalse(key.access)
        self.assertTrue(self.api.edited)

    def test_worker_cannot_press_admin_buttons(self):
        key = self._issue()
        self.bot.pmk_handle_update({"callback_query": {
            "id": "cb", "data": "vpn:off:%d" % key.id, "from": {"id": WORKER_CHAT},
            "message": {"message_id": 7, "chat": {"id": WORKER_CHAT}, "text": ""}}})
        self.assertTrue(key.access)
        self.assertEqual(self.api.answers[-1], "Нет доступа")

    def test_new_key_changes_uuid(self):
        key = self._issue()
        old = key.uuid
        key.action_pmk_new_key()
        self.assertNotEqual(key.uuid, old)
        self.assertEqual(key.state, "pending")


@tagged("post_install", "-at_install")
class TestPmkVpnSyncHttp(HttpCase):

    def test_sync_needs_token(self):
        self.env["ir.config_parameter"].sudo().set_param(PARAM_TOKEN, "s3cret")
        bad = self.url_open("/pmk_vpn/sync", data="{}", headers={"X-Pmk-Vpn-Token": "x"})
        self.assertEqual(bad.status_code, 403)
        ok = self.url_open("/pmk_vpn/sync", data="{}", headers={"X-Pmk-Vpn-Token": "s3cret"})
        self.assertEqual(ok.status_code, 200)
        self.assertIn("users", ok.json())
