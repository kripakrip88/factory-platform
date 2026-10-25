# -*- coding: utf-8 -*-
"""Логика бота: меню → этап → «что нужно» → сделка (или задача).

Диалог:
    «➕ Создать сделку» → кнопки этапов → «Что нужно?» → текст или скриншот
    → сделка СД-… создана; всё, что придёт следом, дописывается в неё же,
    пока не нажата «Готово», не начата новая сделка или не прошло
    TIMEOUT_MINUTES тишины.
    «📝 Задача в доработку» (12.10.2026) → «Опишите задачу» → задача в
    проекте «Доработка системы», колонка «Новые»; дописывание — так же.

Меню — список MENU: следующая функция бота (заявка на снабжение и т.п.) —
ещё одна строка в нём и метод-обработчик, без переделки остального.

Группа (13.10.2026): бот только ПИШЕТ в одну общую группу (итоги планёрки,
поступления денег). Подключает её человек с доступом к боту — добавив бота в
группу или командой /connect в ней; чужого добавившего бот покидает. Сделки
и задачи из группы не создаются: читать переписку группы боту незачем, режим
приватности @BotFather оставлен включённым. Отправка — pmk_send_group().

Темы (комнаты) группы: бот пишет в ту тему, где дали /connect. Разные виды
уведомлений — в разные темы: «/connect деньги» в теме «Финансы» — поступления
туда, остальное — в тему простого /connect. Виды — GROUP_KINDS; /where —
куда что идёт.
"""
import base64
import html
import logging
import re
import secrets
from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.tools import plaintext2html

from .telegram_api import TelegramApi

_logger = logging.getLogger(__name__)

PARAM_TOKEN = "pmk_telegram.token"
PARAM_SECRET = "pmk_telegram.webhook_secret"
PARAM_GROUP = "pmk_telegram.group_chat_id"
PARAM_GROUP_TITLE = "pmk_telegram.group_title"
# Тема группы для вида уведомлений: pmk_telegram.thread.<вид>. «main» — всё,
# у чего своей темы нет.
PARAM_THREAD = "pmk_telegram.thread.%s"
# вид → (слово в команде, подпись). Новый вид — строка здесь.
GROUP_KINDS = {
    "main": ("", "Основное"),
    "money": ("деньги", "Поступления денег"),
    "plan": ("планёрка", "Итоги планёрки"),
    "cloud": ("облако", "Новые файлы в Облаке"),
}
WEBHOOK_PATH = "/pmk_telegram/webhook"

BTN_NEW_DEAL = "➕ Создать сделку"
BTN_DEV_TASK = "📝 Задача в доработку"
# (подпись кнопки, метод). Порядок — порядок кнопок в меню.
MENU = [
    (BTN_NEW_DEAL, "_pmk_menu_new_deal"),
    (BTN_DEV_TASK, "_pmk_menu_dev_task"),
]

# Доска «Задачи → Доработка системы» живёт в pmk_theme. Жёсткой зависимости
# нет: без проекта кнопка просто не показывается.
DEV_PROJECT_XMLID = "pmk_theme.project_dev"
DEV_ACTION_XMLID = "pmk_theme.action_dev_tasks"

TIMEOUT_MINUTES = 30
NAME_MAX = 60

ASK_CONTENT = ("Что нужно? Напишите текстом или пришлите скриншот переписки "
               "(можно несколько).")
ASK_TASK = ("Опишите задачу: текстом или скриншотом (можно несколько). "
            "Первая строка станет названием.")


def _esc(text):
    return html.escape(text or "", quote=False)


class PmkTelegramBot(models.AbstractModel):
    _name = "pmk.telegram.bot"
    _description = "Бот в Телеграме"

    # ── связь с Телеграмом ────────────────────────────────────────────────

    def _pmk_api(self):
        icp = self.env["ir.config_parameter"].sudo()
        token = icp.get_param(PARAM_TOKEN)
        # pmk_telegram.api_base — запасной путь до Телеграма (ретранслятор),
        # если прямой с сервера недоступен. Пусто — api.telegram.org.
        return TelegramApi(token, icp.get_param("pmk_telegram.api_base")) if token else None

    @api.model
    def pmk_setup_webhook(self):
        """Включить бота: Телеграм начнёт слать сообщения на наш адрес.

        Запуск из odoo shell: env["pmk.telegram.bot"].pmk_setup_webhook()
        max_connections=1 — сообщения идут строго по одному: альбом из трёх
        скриншотов не превратится в три сделки из-за параллельных запросов.
        """
        icp = self.env["ir.config_parameter"].sudo()
        secret = icp.get_param(PARAM_SECRET)
        if not secret:
            secret = secrets.token_urlsafe(32)
            icp.set_param(PARAM_SECRET, secret)
        base = icp.get_param("web.base.url").rstrip("/")
        api_ = self._pmk_api()
        if not api_:
            raise ValueError(f"Не задан системный параметр {PARAM_TOKEN}")
        return api_.call(
            "setWebhook", url=base + WEBHOOK_PATH, secret_token=secret,
            max_connections=1, allowed_updates=["message", "callback_query"])

    # ── вход ──────────────────────────────────────────────────────────────

    @api.model
    def pmk_handle_update(self, update):
        api_ = self._pmk_api()
        if not api_:
            _logger.warning("Телеграм: нет токена, сообщение пропущено")
            return
        if update.get("callback_query"):
            self._pmk_on_callback(api_, update["callback_query"])
        elif update.get("message"):
            self._pmk_on_message(api_, update["message"])

    # ── группа ────────────────────────────────────────────────────────────

    @api.model
    def pmk_send_group(self, text, reply_markup=None, kind="main"):
        """Сообщение в подключённую группу, в тему этого вида уведомлений.

        Своей темы у вида нет — в тему «main», нет и её — в «Общую».
        Нет связи с Телеграмом — сообщение ложится в очередь
        (pmk.telegram.outbox) и досылается позже; это тоже True.
        False — группы нет или Телеграм отказал.
        """
        return self.pmk_send_group_files(text, [], reply_markup, kind=kind)

    # Подпись к файлу у Телеграма — до 1024 знаков (видимых, без тегов).
    CAPTION_MAX = 1000

    @api.model
    def pmk_send_group_files(self, text, files, reply_markup=None, kind="main"):
        """Сообщение с файлами в группу: первый файл — с текстом и кнопками,
        остальные — следом ответами на него (так они держатся вместе).

        files — [(имя, байты)]. Длинный текст или сбой файла — текст отдельным
        сообщением, а файлы следом: уведомление не теряется из-за вложения.
        Нет связи — в очередь; пока очередь не пуста, новое встаёт за ней.
        """
        Outbox = self.env["pmk.telegram.outbox"].sudo()
        if not self.env["ir.config_parameter"].sudo().get_param(PARAM_GROUP):
            return False
        if Outbox.pmk_pending():
            Outbox.pmk_enqueue(text, files, reply_markup, kind)
            return True
        ok, network_down = self._pmk_group_deliver(text, files, reply_markup, kind)
        if not ok and network_down:
            Outbox.pmk_enqueue(text, files, reply_markup, kind)
            return True
        return ok

    @api.model
    def pmk_send_user(self, user, text, reply_markup=None):
        """Личное сообщение человеку, если у него привязан Телеграм.

        Нет связи — в очередь (как и сообщения в группу). False — Телеграм не
        привязан или Телеграм отказал (например, человек не нажимал Start).
        """
        chat_id = user.sudo().pmk_telegram_id
        if not chat_id:
            return False
        ok, network_down = self._pmk_chat_deliver(chat_id, text, reply_markup)
        if not ok and network_down:
            self.env["pmk.telegram.outbox"].sudo().pmk_enqueue(
                text, [], reply_markup, "user", chat_id=chat_id)
            return True
        return ok

    def _pmk_chat_deliver(self, chat_id, text, reply_markup):
        api_ = self._pmk_api()
        if not api_:
            return False, False
        res = api_.send(chat_id, text, reply_markup)
        return bool(res), getattr(api_, "network_down", False)

    def _pmk_group_deliver(self, text, files, reply_markup, kind):
        """Отправить сейчас. → (дошло, нет_связи)."""
        icp = self.env["ir.config_parameter"].sudo()
        chat_id = icp.get_param(PARAM_GROUP)
        api_ = self._pmk_api()
        if not chat_id or not api_:
            return False, False
        thread = (icp.get_param(PARAM_THREAD % kind)
                  or icp.get_param(PARAM_THREAD % "main"))
        if not files:
            res = api_.send(chat_id, text, reply_markup, thread_id=thread)
            return bool(res), getattr(api_, "network_down", False)
        visible = len(re.sub(r"<[^>]+>", "", text or ""))
        first = None
        if visible <= self.CAPTION_MAX:
            first = api_.send_document(chat_id, files[0], text, reply_markup, thread_id=thread)
            if not first and getattr(api_, "network_down", False):
                return False, True
        if not first:
            first = api_.send(chat_id, text, reply_markup, thread_id=thread)
            if not first:
                return False, getattr(api_, "network_down", False)
            rest = files
        else:
            rest = files[1:]
        for doc in rest:
            api_.send_document(chat_id, doc, thread_id=thread,
                               reply_to=first.get("message_id"))
        return True, False

    def _pmk_set_group(self, chat_id, title):
        icp = self.env["ir.config_parameter"].sudo()
        if str(chat_id or "") != (icp.get_param(PARAM_GROUP) or ""):
            # Другая группа — темы старой группы к ней не относятся.
            for kind in GROUP_KINDS:
                icp.set_param(PARAM_THREAD % kind, False)
        icp.set_param(PARAM_GROUP, str(chat_id) if chat_id else False)
        icp.set_param(PARAM_GROUP_TITLE, title or False)

    def _pmk_routes_text(self):
        icp = self.env["ir.config_parameter"].sudo()
        main = icp.get_param(PARAM_THREAD % "main")
        lines = []
        for kind, (_word, label) in GROUP_KINDS.items():
            own = icp.get_param(PARAM_THREAD % kind)
            where = ("тема №%s" % own if own else
                     "как основное" if kind != "main" else "«Общая»")
            if kind != "main" and not own and main:
                where = "как основное (тема №%s)" % main
            lines.append("• %s — %s" % (label, where))
        return "\n".join(lines)

    def _pmk_on_group_message(self, api_, message):
        chat = message["chat"]
        icp = self.env["ir.config_parameter"].sudo()
        # Группа стала супергруппой — у неё новый ID, старый перестаёт работать.
        if message.get("migrate_to_chat_id"):
            if icp.get_param(PARAM_GROUP) == str(chat["id"]):
                icp.set_param(PARAM_GROUP, str(message["migrate_to_chat_id"]))
            return
        text = (message.get("text") or "").strip()
        words = text.split()
        command = words[0].split("@")[0].lower() if text.startswith("/") else ""
        arg = " ".join(words[1:]).strip().lower()
        added_me = any(m.get("id") == api_.bot_id
                       for m in message.get("new_chat_members") or [])
        if not added_me and command not in ("/connect", "/disconnect", "/where"):
            return
        # Тема, где написали: у сообщения в теме — её номер; «Общая» — без.
        thread = (message.get("message_thread_id")
                  if message.get("is_topic_message") else None)
        user = self._pmk_user(message.get("from") or {})
        if not user:
            # Добавил или зовёт посторонний — уходим: бот пишет в группу
            # данные Odoo, и группу выбирают только свои.
            if added_me:
                api_.leave_chat(chat["id"])
            return
        if command == "/disconnect":
            if icp.get_param(PARAM_GROUP) == str(chat["id"]):
                self._pmk_set_group(False, False)
                api_.send(chat["id"], "Группа отключена: больше ничего сюда не пишу.",
                          thread_id=thread)
            return
        if command == "/where":
            if icp.get_param(PARAM_GROUP) == str(chat["id"]):
                api_.send(chat["id"], "Куда пишу:\n" + self._pmk_routes_text(),
                          thread_id=thread)
            return
        kind = next((k for k, (word, _l) in GROUP_KINDS.items()
                     if word and arg.startswith(word.replace("ё", "е"))
                     or word and arg.startswith(word)), "main")
        if arg and kind == "main":
            words_hint = ", ".join(w for w, _l in GROUP_KINDS.values() if w)
            api_.send(chat["id"], "Не знаю вид «%s». Есть: %s — или просто "
                      "/connect для основного." % (_esc(arg), words_hint),
                      thread_id=thread)
            return
        self._pmk_set_group(chat["id"], chat.get("title"))
        icp.set_param(PARAM_THREAD % kind, str(thread) if thread else False)
        label = GROUP_KINDS[kind][1]
        api_.send(chat["id"],
                  "✅ Группа подключена. %s — пишу сюда.\n\n%s\n\nДругое уведомление в другую "
                  "тему — /connect с его словом там (например «/connect деньги»). "
                  "Куда что — /where. Отключить — /disconnect"
                  % (label, self._pmk_routes_text()),
                  thread_id=thread)

    def _pmk_user(self, tg_user):
        return self.env["res.users"].sudo().search(
            [("pmk_telegram_id", "=", str(tg_user.get("id")))], limit=1)

    def _pmk_session(self, chat_id, user):
        Session = self.env["pmk.telegram.session"].sudo()
        session = Session.search([("chat_id", "=", str(chat_id))], limit=1)
        if not session:
            session = Session.create({"chat_id": str(chat_id), "user_id": user.id})
        # Блокировка строки: второе сообщение того же чата ждёт, пока первое
        # не создаст сделку (страховка к max_connections=1).
        self.env.cr.execute(
            "SELECT id FROM pmk_telegram_session WHERE id = %s FOR UPDATE",
            [session.id])
        session.invalidate_recordset()
        if session.user_id != user:
            session.user_id = user
        # Долгая тишина — диалог сброшен: сообщение через день не должно
        # молча дописаться во вчерашнюю сделку.
        if (session.state != "idle" and session.last_activity
                and fields.Datetime.now() - session.last_activity
                > timedelta(minutes=TIMEOUT_MINUTES)):
            session.write({"state": "idle", "lead_id": False, "task_id": False,
                           "stage_id": False, "media_group_id": False})
        return session

    def _pmk_dev_project(self):
        return self.env.ref(DEV_PROJECT_XMLID, raise_if_not_found=False)

    def _pmk_menu(self, user):
        """Пункты меню этого человека.

        Кнопка задачи — только если доска есть и у человека есть доступ к
        проектам: без прав Odoo всё равно не даст создать задачу, а кнопка,
        которая всегда отвечает отказом, хуже, чем никакой.
        """
        allowed = []
        for label, method in MENU:
            if label == BTN_DEV_TASK and not (
                    self._pmk_dev_project()
                    and user.has_group("project.group_project_user")):
                continue
            allowed.append((label, method))
        return allowed

    def _pmk_menu_markup(self, user):
        return {"keyboard": [[{"text": label}] for label, _m in self._pmk_menu(user)],
                "resize_keyboard": True, "is_persistent": True}

    # ── сообщения ─────────────────────────────────────────────────────────

    def _pmk_on_message(self, api_, message):
        chat_id = message["chat"]["id"]
        if message["chat"].get("type") in ("group", "supergroup"):
            self._pmk_on_group_message(api_, message)
            return
        if message["chat"].get("type") != "private":
            return
        user = self._pmk_user(message.get("from") or {})
        if not user:
            api_.send(chat_id,
                      "Нет доступа. Ваш Telegram ID: <code>%s</code> — передайте "
                      "его администратору." % _esc(str(message["from"]["id"])))
            return
        # Вебхук приходит публичным пользователем (язык en_US) — без этого
        # этапы и колонки бот показывал бы английскими переводами (20.10.2026:
        # Владимиру «Request / Costing»). Говорим на языке того, кто пишет.
        self = self.with_context(lang=user.lang or "ru_RU")  # noqa: PLW0642
        session = self._pmk_session(chat_id, user)
        text = (message.get("text") or "").strip()

        if text.startswith("/start") or text.startswith("/menu"):
            session.write({"state": "idle", "lead_id": False, "task_id": False,
                           "media_group_id": False})
            api_.send(chat_id, "Здравствуйте, %s! Выберите действие в меню "
                      "внизу." % _esc(user.name), self._pmk_menu_markup(user))
            return
        for label, method in self._pmk_menu(user):
            if text == label:
                getattr(self, method)(api_, session)
                session.last_activity = fields.Datetime.now()
                return

        if session.state in ("await_content", "await_task", "collecting"):
            self._pmk_take_content(api_, session, message)
            session.last_activity = fields.Datetime.now()
        elif session.state == "await_stage":
            api_.send(chat_id, "Сначала выберите этап кнопкой выше.")
        else:
            api_.send(chat_id, "Выберите действие в меню внизу.",
                      self._pmk_menu_markup(user))

    def _pmk_deal_stages(self):
        """Этапы, которые человек может выбрать в боте.

        Без «Разобрал ассистент» (pmk_ai_mail.stage_ai): это колонка, куда ИИ
        складывает разобранные письма, — вручную туда сделку не кладут
        (Антон, 25.10.2026).
        """
        stages = self.env["crm.stage"].sudo().search([], order="sequence, id")
        ai = self.env.ref("pmk_ai_mail.stage_ai", raise_if_not_found=False)
        return stages - ai if ai else stages

    def _pmk_menu_new_deal(self, api_, session):
        stages = self._pmk_deal_stages()
        session.write({"state": "await_stage", "lead_id": False, "task_id": False,
                       "stage_id": False, "media_group_id": False})
        api_.send(session.chat_id, "Этап сделки?", {"inline_keyboard": [
            [{"text": s.name, "callback_data": f"stage:{s.id}"}] for s in stages]})

    def _pmk_menu_dev_task(self, api_, session):
        session.write({"state": "await_task", "lead_id": False, "task_id": False,
                       "stage_id": False, "media_group_id": False})
        api_.send(session.chat_id, ASK_TASK)

    # ── кнопки под сообщениями ────────────────────────────────────────────

    def _pmk_on_callback(self, api_, cq):
        data = cq.get("data") or ""
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        # Листалка картинок: листать может любой, кто видит сообщение (в
        # группе — все участники), — это только просмотр. Запись листалки
        # должна принадлежать этому же чату и сообщению.
        if data.startswith("car:"):
            rec_id, _sep, idx = data[4:].partition(":")
            car = self.env["pmk.telegram.carousel"].sudo().browse(int(rec_id)).exists()
            if (car and car.chat_id == str(chat_id)
                    and car.message_id == msg.get("message_id") and idx.isdigit()):
                if int(idx) != car.index:
                    car.pmk_show(api_, int(idx))
                api_.answer_callback(cq["id"])
            else:
                api_.answer_callback(cq["id"], "Сообщение устарело")
            return
        # Кнопки макетов (примеры заданий и сводок) — честно говорим, что это пример.
        if data.startswith("demo:"):
            api_.answer_callback(cq["id"], "Это пример — кнопка пока не работает")
            return
        user = self._pmk_user(cq.get("from") or {})
        if not user or not chat_id:
            api_.answer_callback(cq["id"], "Нет доступа")
            return
        self = self.with_context(lang=user.lang or "ru_RU")  # noqa: PLW0642 — см. _pmk_on_message
        session = self._pmk_session(chat_id, user)

        if data.startswith("stage:"):
            stage = self.env["crm.stage"].sudo().browse(int(data[6:])).exists()
            stage = stage & self._pmk_deal_stages()
            if session.state != "await_stage" or not stage:
                api_.answer_callback(cq["id"], "Кнопка устарела — начните заново")
                return
            session.write({"state": "await_content", "stage_id": stage.id,
                           "last_activity": fields.Datetime.now()})
            api_.answer_callback(cq["id"])
            api_.edit(chat_id, msg["message_id"],
                      "Этап: <b>%s</b>" % _esc(stage.name))
            api_.send(chat_id, ASK_CONTENT)
        elif data.startswith("done:"):
            # done:task:5 / done:lead:5; «done:5» — кнопки первой версии (сделка).
            parts = data.split(":")
            model = "project.task" if parts[1] == "task" else "crm.lead"
            record = self.env[model].sudo().browse(int(parts[-1])).exists()
            if record and self._pmk_target(session) == record:
                session.write({"state": "idle", "lead_id": False, "task_id": False,
                               "media_group_id": False})
            api_.answer_callback(cq["id"], "Записано")
            if record:
                api_.edit(chat_id, msg["message_id"],
                          "✅ %s записана, %s «%s»." % (
                              _esc(self._pmk_label(record)),
                              "колонка" if model == "project.task" else "этап",
                              _esc(record.stage_id.name)),
                          self._pmk_open_markup(record, done=False))
        else:
            api_.answer_callback(cq["id"])

    # ── содержимое → сделка ───────────────────────────────────────────────

    def _pmk_take_content(self, api_, session, message):
        chat_id = session.chat_id
        text = (message.get("text") or message.get("caption") or "").strip()
        files = self._pmk_files(api_, message)
        if not text and not files:
            if message.get("photo") or message.get("document"):
                api_.send(chat_id, "Не удалось скачать файл (больше 20 МБ или "
                                   "Телеграм не отдал). Пришлите ещё раз.")
            else:
                api_.send(chat_id, "Понимаю текст, скриншоты и файлы — "
                                   "голосовые и стикеры пока нет.")
            return

        group = message.get("media_group_id")
        same_album = bool(group) and group == session.media_group_id
        session.media_group_id = group or False
        user = session.user_id

        if session.state == "await_content":
            lead = self._pmk_create_deal(user, session.stage_id, text, files)
            session.write({"state": "collecting", "lead_id": lead.id})
            api_.send(chat_id,
                      "✅ <b>%s</b> создана, этап «%s».\nЗабыли что-то — "
                      "пришлите, добавлю в эту же сделку." % (
                          _esc(self._pmk_label(lead)),
                          _esc(lead.stage_id.name)),
                      self._pmk_open_markup(lead))
        elif session.state == "await_task":
            task = self._pmk_create_dev_task(user, text, files)
            if not task:
                session.write({"state": "idle"})
                api_.send(chat_id, "Доска «Доработка системы» не найдена.",
                          self._pmk_menu_markup(session.user_id))
                return
            session.write({"state": "collecting", "task_id": task.id})
            api_.send(chat_id,
                      "✅ Задача <b>%s</b> создана, колонка «%s».\nЗабыли что-то — "
                      "пришлите, добавлю в эту же задачу." % (
                          _esc(task.name), _esc(task.stage_id.name)),
                      self._pmk_open_markup(task))
        else:
            record = self._pmk_target(session)
            if not record:
                session.write({"state": "idle", "lead_id": False, "task_id": False})
                api_.send(chat_id, "Запись не найдена — начните заново.",
                          self._pmk_menu_markup(session.user_id))
                return
            self._pmk_append(user, record, text, files)
            if not same_album:
                api_.send(chat_id, "➕ Добавлено в %s."
                          % _esc(self._pmk_label(record)),
                          self._pmk_open_markup(record))

    def _pmk_files(self, api_, message):
        """[(имя, байты)] из фото (самый крупный размер) или файла."""
        stamp = fields.Datetime.now().strftime("%Y%m%d_%H%M%S")
        if message.get("photo"):
            best = max(message["photo"], key=lambda p: p.get("file_size") or 0)
            raw = api_.download(best["file_id"])
            return [(f"telegram_{stamp}_{message.get('message_id')}.jpg", raw)] if raw else []
        if message.get("document"):
            doc = message["document"]
            raw = api_.download(doc["file_id"])
            name = doc.get("file_name") or f"telegram_{stamp}"
            return [(name, raw)] if raw else []
        return []

    def _pmk_target(self, session):
        """Сделка или задача, в которую сейчас дописываем."""
        return (session.task_id or session.lead_id).exists()

    def _pmk_deal_name(self, user, text, fallback="Запрос из Телеграма"):
        line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if line:
            return line if len(line) <= NAME_MAX else line[:NAME_MAX - 1].rstrip() + "…"
        tz = pytz.timezone(user.tz or "Asia/Vladivostok")
        now = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
        return "%s %s" % (fallback, now.strftime("%d.%m %H:%M"))

    def _pmk_create_deal(self, user, stage, text, files):
        lead = self.env["crm.lead"].with_user(user).create({
            "name": self._pmk_deal_name(user, text),
            "type": "opportunity",
            "stage_id": stage.id,
            "user_id": user.id,
            "pmk_source": "telegram",
            "description": plaintext2html(text) if text else False,
        })
        self._pmk_post(user, lead, text, files)
        return lead

    def _pmk_create_dev_task(self, user, text, files):
        """Задача на доске «Доработка системы», первая колонка («Новые»)."""
        project = self._pmk_dev_project()
        if not project:
            return None
        stage = self.env["project.task.type"].sudo().search(
            [("project_ids", "in", project.id)], order="sequence, id", limit=1)
        # sudo — не ради обхода прав (их проверяет меню: кнопка только при
        # доступе к проектам), а из-за ядра. «Ответственные» (user_ids) — связь
        # с res.users, а у res.users _allow_sudo_commands = False: такую связь
        # Odoo проверяет от имени ПЕРВОГО пользователя транзакции, а вебхук
        # Телеграма приходит публичным пользователем → AccessError (12.10.2026).
        # Проверка пропускается только у sudo-записи; uid остаётся человеком —
        # автор, создатель и ответственный задачи он.
        task = self.env["project.task"].with_user(user).sudo().create({
            "name": self._pmk_deal_name(user, text, "Задача из Телеграма"),
            "project_id": project.id,
            "stage_id": stage.id,
            "user_ids": [(6, 0, [user.id])],
            "description": plaintext2html(text) if text else False,
        })
        self._pmk_post(user, task, text, files)
        return task

    def _pmk_append(self, user, record, text, files):
        if text:
            record = record.with_user(user)
            record.description = (record.description or "") + plaintext2html(text)
        self._pmk_post(user, record, text, files)

    def _pmk_post(self, user, record, text, files):
        """Запись в ленту: текст и скриншоты — видно с компьютера."""
        attachments = self.env["ir.attachment"].with_user(user).create([{
            "name": name,
            "datas": base64.b64encode(raw),
            "res_model": record._name,
            "res_id": record.id,
        } for name, raw in files])
        body = plaintext2html("Из Телеграма:\n" + text) if text else \
            plaintext2html("Из Телеграма")
        record.with_user(user).message_post(
            body=body, attachment_ids=attachments.ids,
            message_type="comment", subtype_xmlid="mail.mt_note")

    def _pmk_label(self, record):
        if record._name == "crm.lead":
            return record.pmk_number or record.name
        return record.name

    def _pmk_open_markup(self, record, done=True):
        kind = "task" if record._name == "project.task" else "lead"
        row = []
        if done:
            row.append({"text": "Готово", "callback_data": f"done:{kind}:{record.id}"})
        base = (self.env["ir.config_parameter"].sudo()
                .get_param("web.base.url") or "").rstrip("/")
        # Телеграм принимает в кнопке только настоящий https-адрес.
        if base.startswith("https://"):
            path = (f"/odoo/action-{DEV_ACTION_XMLID}/{record.id}" if kind == "task"
                    else f"/odoo/crm/{record.id}")
            row.append({"text": "Открыть в Odoo", "url": base + path})
        return {"inline_keyboard": [row]} if row else None
