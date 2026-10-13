# -*- coding: utf-8 -*-
"""Диалог бота целиком — на подставном Телеграме, без сети."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models import bot as bot_mod

CHAT = 3578814


class FakeApi:
    bot_id = 8636440433

    def __init__(self):
        self.sent = []      # (chat_id, text, markup)
        self.edited = []
        self.answers = []
        self.left = []

    def leave_chat(self, chat_id):
        self.left.append(chat_id)

    def send(self, chat_id, text, reply_markup=None, thread_id=None):
        self.sent.append((chat_id, text, reply_markup))
        self.threads = getattr(self, "threads", []) + [thread_id]
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
        self._click(f"done:lead:{lead.id}")
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
        self.assertIn("меню", self.api.sent[-1][1])
        self.assertEqual(self.api.sent[-1][2]["keyboard"][0][0]["text"],
                         bot_mod.BTN_NEW_DEAL)
        self.assertFalse(self.env["crm.lead"].search(
            [("user_id", "=", self.user.id)]))

    def test_old_stage_button_ignored(self):
        self._start_deal()
        self._msg(text="Первое")
        self._click(f"stage:{self.stage.id}")
        self.assertIn("устарела", self.api.answers[-1])


@tagged("post_install", "-at_install")
class TestTelegramDevTask(TestTelegramBot):
    """«📝 Задача в доработку» → задача на доске, колонка «Новые»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Доработка системы"})
        cls.stage_new = cls.env["project.task.type"].create(
            {"name": "Новые", "sequence": 1, "project_ids": [(4, cls.project.id)]})
        cls.env["project.task.type"].create(
            {"name": "В работе", "sequence": 2, "project_ids": [(4, cls.project.id)]})
        cls.user.group_ids = [(4, cls.env.ref("project.group_project_user").id)]

    def setUp(self):
        super().setUp()
        patcher = patch.object(type(self.env["pmk.telegram.bot"]), "_pmk_dev_project",
                               lambda _self: self.project)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tasks(self):
        return self.env["project.task"].search([("project_id", "=", self.project.id)])

    def test_menu_has_task_button(self):
        self._msg(text="/start")
        labels = [row[0]["text"] for row in self.api.sent[-1][2]["keyboard"]]
        self.assertEqual(labels, [bot_mod.BTN_NEW_DEAL, bot_mod.BTN_DEV_TASK])

    def test_no_project_rights_no_button(self):
        self.user.group_ids = [(3, self.env.ref("project.group_project_user").id),
                               (3, self.env.ref("project.group_project_manager").id)]
        self.assertFalse(self.user.has_group("project.group_project_user"))
        self._msg(text="/start")
        labels = [row[0]["text"] for row in self.api.sent[-1][2]["keyboard"]]
        self.assertEqual(labels, [bot_mod.BTN_NEW_DEAL])
        self._msg(text=bot_mod.BTN_DEV_TASK)
        self.assertNotEqual(self._session().state, "await_task")

    def test_text_creates_task_in_first_column(self):
        self._msg(text=bot_mod.BTN_DEV_TASK)
        self.assertEqual(self._session().state, "await_task")
        self._msg(text="Кнопка «Печать» не видна\nв расчёте на узком экране")
        task = self._tasks()
        self.assertEqual(len(task), 1)
        self.assertEqual(task.name, "Кнопка «Печать» не видна")
        self.assertEqual(task.stage_id, self.stage_new)
        self.assertIn("узком экране", task.description)
        self.assertFalse(self.env["crm.lead"].search([("user_id", "=", self.user.id)]))
        self.assertIn("Задача", self.api.sent[-1][1])
        urls = [b.get("url") for b in self.api.sent[-1][2]["inline_keyboard"][0]]
        self.assertIn(
            f"https://erppark.ru/odoo/action-{bot_mod.DEV_ACTION_XMLID}/{task.id}", urls)

    def test_task_from_public_webhook_transaction(self):
        """Вебхук приходит публичным пользователем (auth="public").

        Связь «Ответственные» → res.users Odoo проверяет от имени ПЕРВОГО
        пользователя транзакции; на живом это публичный — и задача падала
        с AccessError (12.10.2026), хотя в тестах (суперпользователь) — нет.
        """
        transaction = self.env.transaction
        saved = transaction.default_env
        transaction.default_env = self.env(user=self.env.ref("base.public_user"))
        self.addCleanup(setattr, transaction, "default_env", saved)
        self._msg(text=bot_mod.BTN_DEV_TASK)
        self._msg(text="Задача с публичного вебхука")
        task = self._tasks()
        self.assertEqual(len(task), 1)
        self.assertEqual(task.user_ids, self.user)
        self.assertEqual(task.create_uid, self.user)

    def test_screenshot_then_text_append_to_task(self):
        self._msg(text=bot_mod.BTN_DEV_TASK)
        self._msg(photo=[{"file_id": "shot", "file_size": 5}])
        task = self._tasks()
        self.assertTrue(task.name.startswith("Задача из Телеграма"))
        self._msg(text="Вот тут съезжает")
        self.assertIn("съезжает", task.description)
        atts = self.env["ir.attachment"].search(
            [("res_model", "=", "project.task"), ("res_id", "=", task.id)])
        self.assertEqual(len(atts), 1)
        self._click(f"done:task:{task.id}")
        self.assertEqual(self._session().state, "idle")
        self.assertEqual(len(self._tasks()), 1)

    def test_old_done_button_still_works(self):
        self._start_deal()
        self._msg(text="Первое")
        lead = self._session().lead_id
        self._click(f"done:{lead.id}")
        self.assertEqual(self._session().state, "idle")


@tagged("post_install", "-at_install")
class TestTelegramGroup(TransactionCase):
    """Группа: подключает только свой, пишет туда только бот."""

    GROUP = -100777

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create({
            "name": "Антон Тест", "login": "tg_anton_grp",
            "group_ids": [(4, cls.env.ref("sales_team.group_sale_manager").id)],
            "pmk_telegram_id": str(CHAT),
        })

    def setUp(self):
        super().setUp()
        self.api = FakeApi()
        patcher = patch.object(type(self.env["pmk.telegram.bot"]), "_pmk_api",
                               lambda _self: self.api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bot = self.env["pmk.telegram.bot"].sudo()
        self.icp = self.env["ir.config_parameter"].sudo()

    def _group_msg(self, from_id=CHAT, chat_id=None, **extra):
        msg = {"message_id": 1, "from": {"id": from_id},
               "chat": {"id": chat_id or self.GROUP, "type": "group", "title": "Цех"}}
        msg.update(extra)
        self.bot.pmk_handle_update({"message": msg})

    def _added(self, from_id=CHAT):
        self._group_msg(from_id=from_id, new_chat_members=[
            {"id": FakeApi.bot_id, "is_bot": True}])

    def test_owner_adds_bot_connects_group(self):
        self._added()
        self.assertEqual(self.icp.get_param(bot_mod.PARAM_GROUP), str(self.GROUP))
        self.assertEqual(self.icp.get_param(bot_mod.PARAM_GROUP_TITLE), "Цех")
        self.assertIn("Группа подключена", self.api.sent[-1][1])

    def test_stranger_adds_bot_bot_leaves(self):
        self._added(from_id=999)
        self.assertEqual(self.api.left, [self.GROUP])
        self.assertFalse(self.icp.get_param(bot_mod.PARAM_GROUP))

    def test_connect_command_with_bot_name(self):
        self._group_msg(text="/connect@Dv_laba_bot")
        self.assertEqual(self.icp.get_param(bot_mod.PARAM_GROUP), str(self.GROUP))

    def test_disconnect(self):
        self._added()
        self._group_msg(text="/disconnect")
        self.assertFalse(self.icp.get_param(bot_mod.PARAM_GROUP))

    def test_group_chatter_ignored(self):
        self._added()
        sent = len(self.api.sent)
        self._group_msg(text=bot_mod.BTN_NEW_DEAL)
        self._group_msg(text="обычная переписка")
        self.assertEqual(len(self.api.sent), sent)
        self.assertFalse(self.env["pmk.telegram.session"].search(
            [("chat_id", "=", str(self.GROUP))]))

    def test_supergroup_migration_keeps_group(self):
        self._added()
        self._group_msg(migrate_to_chat_id=-1009999)
        self.assertEqual(self.icp.get_param(bot_mod.PARAM_GROUP), "-1009999")

    def test_send_group(self):
        self.assertFalse(self.bot.pmk_send_group("нет группы"))
        self._added()
        self.assertTrue(self.bot.pmk_send_group("📋 Планёрка"))
        self.assertEqual(self.api.sent[-1][:2], (str(self.GROUP), "📋 Планёрка"))


@tagged("post_install", "-at_install")
class TestTelegramGroupTopics(TestTelegramGroup):
    """Группа с темами: пишем туда, где дали /connect; виды — по темам."""

    def _topic_cmd(self, text, thread):
        self._group_msg(text=text, message_thread_id=thread, is_topic_message=True)

    def test_connect_in_topic_remembers_topic(self):
        self._topic_cmd("/connect@Dv_laba_bot", 11)
        self.assertEqual(self.icp.get_param(bot_mod.PARAM_THREAD % "main"), "11")
        self.assertEqual(self.api.threads[-1], 11)
        self.bot.pmk_send_group("всё")
        self.assertEqual(self.api.threads[-1], "11")

    def test_money_and_plan_topics(self):
        self._topic_cmd("/connect@Dv_laba_bot", 11)
        self._topic_cmd("/connect@Dv_laba_bot деньги", 22)
        self._topic_cmd("/connect@Dv_laba_bot планерка", 33)
        self.bot.pmk_send_group("💰", kind="money")
        self.assertEqual(self.api.threads[-1], "22")
        self.bot.pmk_send_group("📋", kind="plan")
        self.assertEqual(self.api.threads[-1], "33")
        self.bot.pmk_send_group("прочее")
        self.assertEqual(self.api.threads[-1], "11")

    def test_kind_without_topic_falls_back_to_main(self):
        self._topic_cmd("/connect@Dv_laba_bot", 11)
        self.bot.pmk_send_group("💰", kind="money")
        self.assertEqual(self.api.threads[-1], "11")

    def test_unknown_word_not_connected(self):
        self._topic_cmd("/connect@Dv_laba_bot склад", 44)
        self.assertIn("Не знаю вид", self.api.sent[-1][1])
        self.assertFalse(self.icp.get_param(bot_mod.PARAM_GROUP))

    def test_where_lists_routes(self):
        self._topic_cmd("/connect@Dv_laba_bot деньги", 22)
        self._topic_cmd("/where@Dv_laba_bot", 22)
        self.assertIn("Поступления денег — тема №22", self.api.sent[-1][1])

    def test_general_topic_has_no_thread(self):
        self._group_msg(text="/connect@Dv_laba_bot")
        self.assertFalse(self.icp.get_param(bot_mod.PARAM_THREAD % "main"))
        self.bot.pmk_send_group("всё")
        self.assertFalse(self.api.threads[-1])
