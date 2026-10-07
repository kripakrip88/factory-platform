# -*- coding: utf-8 -*-
"""Логика бота: меню → этап → «что нужно» → сделка.

Диалог:
    «➕ Создать сделку» → кнопки этапов → «Что нужно?» → текст или скриншот
    → сделка СД-… создана; всё, что придёт следом, дописывается в неё же,
    пока не нажата «Готово», не начата новая сделка или не прошло
    TIMEOUT_MINUTES тишины.

Меню — список MENU: следующая функция бота (заявка на снабжение и т.п.) —
ещё одна строка в нём и метод-обработчик, без переделки остального.
"""
import base64
import html
import logging
import secrets
from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.tools import plaintext2html

from .telegram_api import TelegramApi

_logger = logging.getLogger(__name__)

PARAM_TOKEN = "pmk_telegram.token"
PARAM_SECRET = "pmk_telegram.webhook_secret"
WEBHOOK_PATH = "/pmk_telegram/webhook"

BTN_NEW_DEAL = "➕ Создать сделку"
# (подпись кнопки, метод). Порядок — порядок кнопок в меню.
MENU = [
    (BTN_NEW_DEAL, "_pmk_menu_new_deal"),
]

TIMEOUT_MINUTES = 30
NAME_MAX = 60

ASK_CONTENT = ("Что нужно? Напишите текстом или пришлите скриншот переписки "
               "(можно несколько).")


def _esc(text):
    return html.escape(text or "", quote=False)


class PmkTelegramBot(models.AbstractModel):
    _name = "pmk.telegram.bot"
    _description = "Бот в Телеграме"

    # ── связь с Телеграмом ────────────────────────────────────────────────

    def _pmk_api(self):
        token = self.env["ir.config_parameter"].sudo().get_param(PARAM_TOKEN)
        return TelegramApi(token) if token else None

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
            session.write({"state": "idle", "lead_id": False,
                           "stage_id": False, "media_group_id": False})
        return session

    def _pmk_menu_markup(self):
        return {"keyboard": [[{"text": label}] for label, _m in MENU],
                "resize_keyboard": True, "is_persistent": True}

    # ── сообщения ─────────────────────────────────────────────────────────

    def _pmk_on_message(self, api_, message):
        chat_id = message["chat"]["id"]
        if message["chat"].get("type") != "private":
            return
        user = self._pmk_user(message.get("from") or {})
        if not user:
            api_.send(chat_id,
                      "Нет доступа. Ваш Telegram ID: <code>%s</code> — передайте "
                      "его администратору." % _esc(str(message["from"]["id"])))
            return
        session = self._pmk_session(chat_id, user)
        text = (message.get("text") or "").strip()

        if text.startswith("/start") or text.startswith("/menu"):
            session.write({"state": "idle", "lead_id": False,
                           "media_group_id": False})
            api_.send(chat_id, "Здравствуйте, %s! Выберите действие в меню "
                      "внизу." % _esc(user.name), self._pmk_menu_markup())
            return
        for label, method in MENU:
            if text == label:
                getattr(self, method)(api_, session)
                session.last_activity = fields.Datetime.now()
                return

        if session.state in ("await_content", "collecting"):
            self._pmk_take_content(api_, session, message)
            session.last_activity = fields.Datetime.now()
        elif session.state == "await_stage":
            api_.send(chat_id, "Сначала выберите этап кнопкой выше.")
        else:
            api_.send(chat_id, "Чтобы записать обращение, нажмите «%s»."
                      % BTN_NEW_DEAL, self._pmk_menu_markup())

    def _pmk_menu_new_deal(self, api_, session):
        stages = self.env["crm.stage"].sudo().search([], order="sequence, id")
        session.write({"state": "await_stage", "lead_id": False,
                       "stage_id": False, "media_group_id": False})
        api_.send(session.chat_id, "Этап сделки?", {"inline_keyboard": [
            [{"text": s.name, "callback_data": f"stage:{s.id}"}] for s in stages]})

    # ── кнопки под сообщениями ────────────────────────────────────────────

    def _pmk_on_callback(self, api_, cq):
        data = cq.get("data") or ""
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        user = self._pmk_user(cq.get("from") or {})
        if not user or not chat_id:
            api_.answer_callback(cq["id"], "Нет доступа")
            return
        session = self._pmk_session(chat_id, user)

        if data.startswith("stage:"):
            stage = self.env["crm.stage"].sudo().browse(int(data[6:])).exists()
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
            lead = self.env["crm.lead"].sudo().browse(int(data[5:])).exists()
            if session.lead_id == lead:
                session.write({"state": "idle", "lead_id": False,
                               "media_group_id": False})
            api_.answer_callback(cq["id"], "Записано")
            if lead:
                api_.edit(chat_id, msg["message_id"],
                          "✅ %s записана, этап «%s»." % (
                              _esc(self._pmk_deal_label(lead)),
                              _esc(lead.stage_id.name)),
                          self._pmk_open_markup(lead, done=False))
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
                          _esc(self._pmk_deal_label(lead)),
                          _esc(lead.stage_id.name)),
                      self._pmk_open_markup(lead))
        else:
            lead = session.lead_id
            if not lead.exists():
                session.write({"state": "idle", "lead_id": False})
                api_.send(chat_id, "Сделка не найдена — начните заново.",
                          self._pmk_menu_markup())
                return
            self._pmk_append(user, lead, text, files)
            if not same_album:
                api_.send(chat_id, "➕ Добавлено в %s."
                          % _esc(self._pmk_deal_label(lead)),
                          self._pmk_open_markup(lead))

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

    def _pmk_deal_name(self, user, text):
        line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if line:
            return line if len(line) <= NAME_MAX else line[:NAME_MAX - 1].rstrip() + "…"
        tz = pytz.timezone(user.tz or "Asia/Vladivostok")
        now = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
        return "Запрос из Телеграма %s" % now.strftime("%d.%m %H:%M")

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

    def _pmk_append(self, user, lead, text, files):
        if text:
            lead = lead.with_user(user)
            lead.description = (lead.description or "") + plaintext2html(text)
        self._pmk_post(user, lead, text, files)

    def _pmk_post(self, user, lead, text, files):
        """Запись в ленту сделки: текст и скриншоты — видно с компьютера."""
        attachments = self.env["ir.attachment"].with_user(user).create([{
            "name": name,
            "datas": base64.b64encode(raw),
            "res_model": "crm.lead",
            "res_id": lead.id,
        } for name, raw in files])
        body = plaintext2html("Из Телеграма:\n" + text) if text else \
            plaintext2html("Из Телеграма")
        lead.with_user(user).message_post(
            body=body, attachment_ids=attachments.ids,
            message_type="comment", subtype_xmlid="mail.mt_note")

    def _pmk_deal_label(self, lead):
        return lead.pmk_number or lead.name

    def _pmk_open_markup(self, lead, done=True):
        row = []
        if done:
            row.append({"text": "Готово", "callback_data": f"done:{lead.id}"})
        base = (self.env["ir.config_parameter"].sudo()
                .get_param("web.base.url") or "").rstrip("/")
        # Телеграм принимает в кнопке только настоящий https-адрес.
        if base.startswith("https://"):
            row.append({"text": "Открыть в Odoo",
                        "url": f"{base}/odoo/crm/{lead.id}"})
        return {"inline_keyboard": [row]} if row else None
