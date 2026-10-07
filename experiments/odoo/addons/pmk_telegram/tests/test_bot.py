# -*- coding: utf-8 -*-
"""Диалог бота целиком — на подставном Телеграме, без сети."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models import bot as bot_mod

CHAT = 3578814


class FakeApi:
    def __init__(self):
        self.sent = []      # (chat_id, text, markup)
        self.edited = []
        self.answers = []

    def send(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        return {"message_id": len(self.sent)}

    def edit(self, chat_id, message_id, text, reply_markup=None):
        self.edited.append((chat_id, message_id, text, reply_markup))

    def answer_callback(self, callback_id, text=None):
        self.answers.append(text)

    def download(self, file_id):
        return b"\x89PNG fake " + file_id.encode()

    def call(self, method, **params):
        return True


@tagged("post_install", "-at_install")
class TestTelegramBot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create({
            "name": "Антон Тест", "login": "tg_anton_test",
            "group_ids": [(4, cls.env.ref("sales_team.group_sale_manager").id)],
            "pmk_telegram_id": str(CHAT),
        })
        cls.stage = cls.env["crm.stage"].search([], order="sequence", limit=1)
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://erppark.ru")

    def setUp(self):
        super().setUp()
        self.api = FakeApi()
        patcher = patch.object(type(self.env["pmk.telegram.bot"]), "_pmk_api",
                               lambda _self: self.api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bot = self.env["pmk.telegram.bot"].sudo()
        self.mid = 100

    # ── помощники ─────────────────────────────────────────────────────────

    def _msg(self, from_id=CHAT, **extra):
        self.mid += 1
        msg = {"message_id": self.mid, "chat": {"id": from_id, "type": "private"},
               "from": {"id": from_id}}
        msg.update(extra)
        self.bot.pmk_handle_update({"message": msg})

    def _click(self, data):
        self.bot.pmk_handle_update({"callback_query": {
            "id": "cb", "data": data, "from": {"id": CHAT},
            "message": {"message_id": 1, "chat": {"id": CHAT}}}})

    def _session(self):
        return self.env["pmk.telegram.session"].search([("chat_id", "=", str(CHAT))])

    def _start_deal(self):
        self._msg(text=bot_mod.BTN_NEW_DEAL)
        self._click(f"stage:{self.stage.id}")

    # ── сценарии ──────────────────────────────────────────────────────────

    def test_stranger_gets_his_id(self):
        self._msg(from_id=999, text="/start")
        self.assertIn("Нет доступа", self.api.sent[-1][1])
        self.assertIn("999", self.api.sent[-1][1])
        self.assertFalse(self.env["pmk.telegram.session"].search(
            [("chat_id", "=", "999")]))

    def test_start_shows_menu(self):
        self._msg(text="/start")
        markup = self.api.sent[-1][2]
        self.assertEqual(markup["keyboard"][0][0]["text"], bot_mod.BTN_NEW_DEAL)

    def test_menu_offers_stages(self):
        self._msg(text=bot_mod.BTN_NEW_DEAL)
        buttons = [row[0]["callback_data"] for row in
                   self.api.sent[-1][2]["inline_keyboard"]]
        self.assertIn(f"stage:{self.stage.id}", buttons)
        self.assertEqual(self._session().state, "await_stage")

    def test_text_creates_deal(self):
        self._start_deal()
        self._msg(text="Сталкер, площадка ГРПШ 3 мм, 2 шт\nзвонили сегодня")
        lead = self._session().lead_id
        self.assertTrue(lead)
        self.assertEqual(lead.name, "Сталкер, площадка ГРПШ 3 мм, 2 шт")
        self.assertEqual(lead.type, "opportunity")
        self.assertEqual(lead.stage_id, self.stage)
        self.assertEqual(lead.user_id, self.user)
        self.assertEqual(lead.pmk_source, "telegram")
        self.assertIn("звонили сегодня", lead.description)
        self.assertFalse(lead.partner_id)
        self.assertIn("создана", self.api.sent[-1][1])
        urls = [b.get("url") for b in self.api.sent[-1][2]["inline_keyboard"][0]]
        self.assertIn(f"https://erppark.ru/odoo/crm/{lead.id}", urls)

    def test_long_first_line_is_cut(self):
        self._start_deal()
        self._msg(text="х" * 200)
        name = self._session().lead_id.name
        self.assertEqual(len(name), bot_mod.NAME_MAX)
        self.assertTrue(name.endswith("…"))

    def test_album_is_one_deal_one_reply(self):
        self._start_deal()
        photo = [{"file_id": "small", "file_size": 10},
                 {"file_id": "big", "file_size": 999}]
        for _i in range(3):
            self._msg(photo=photo, media_group_id="alb1")
        leads = self.env["crm.lead"].search([("user_id", "=", self.user.id)])
        self.assertEqual(len(leads), 1)
        self.assertTrue(leads.name.startswith("Запрос из Телеграма"))
        atts = self.env["ir.attachment"].search(
            [("res_model", "=", "crm.lead"), ("res_id", "=", leads.id)])
        self.assertEqual(len(atts), 3)
        self.assertIn(b"big", atts[0].raw)
        replies = [s for s in self.api.sent if "создана" in s[1] or "Добавлено" in s[1]]
        self.assertEqual(len(replies), 1)

    def test_followup_appends_then_done(self):
        self._start_deal()
        self._msg(text="Первое")
        lead = self._session().lead_id
        self._msg(text="Второе")
        self.assertIn("Второе", lead.description)
        self.assertIn("Добавлено", self.api.sent[-1][1])
        self._click(f"done:{lead.id}")
        self.assertEqual(self._session().state, "idle")
        self._msg(text="Третье")
        self.assertNotIn("Третье", lead.description)
        self.assertEqual(self.env["crm.lead"].search_count(
            [("user_id", "=", self.user.id)]), 1)

    def test_silence_resets_dialog(self):
        self._start_deal()
        self._msg(text="Первое")
        lead = self._session().lead_id
        self._session().last_activity = fields.Datetime.now() - timedelta(
            minutes=bot_mod.TIMEOUT_MINUTES + 1)
        self._msg(text="Через час")
        self.assertNotIn("Через час", lead.description)
        self.assertEqual(self._session().state, "idle")

    def test_content_without_menu_hints(self):
        self._msg(text="просто текст")
        self.assertIn(bot_mod.BTN_NEW_DEAL, self.api.sent[-1][1])
        self.assertFalse(self.env["crm.lead"].search(
            [("user_id", "=", self.user.id)]))

    def test_old_stage_button_ignored(self):
        self._start_deal()
        self._msg(text="Первое")
        self._click(f"stage:{self.stage.id}")
        self.assertIn("устарела", self.api.answers[-1])
