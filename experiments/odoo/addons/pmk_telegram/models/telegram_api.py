# -*- coding: utf-8 -*-
"""Тонкий клиент Bot API: только те вызовы, что нужны боту.

Без ORM — чтобы тесты подменяли его целиком (bot._pmk_api) и не ходили в сеть.
Ошибка Телеграма не роняет обработку: вызов пишет её в журнал и возвращает
None. Сделка важнее ответа бота — если ответ не дошёл, запись в Odoo остаётся.
"""
import logging

import requests

_logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT = 15
# Предел Bot API на скачивание файла ботом.
MAX_FILE_BYTES = 20 * 1024 * 1024


class TelegramApi:

    def __init__(self, token):
        self.token = token

    def call(self, method, **params):
        try:
            resp = requests.post(
                f"{API}/bot{self.token}/{method}", json=params, timeout=TIMEOUT)
            data = resp.json()
        except Exception:  # noqa: BLE001 — сеть или не-JSON
            _logger.exception("Телеграм: %s не выполнен", method)
            return None
        if not data.get("ok"):
            _logger.warning("Телеграм: %s → %s", method, data.get("description"))
            return None
        return data.get("result")

    def send(self, chat_id, text, reply_markup=None):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self.call("sendMessage", **params)

    def edit(self, chat_id, message_id, text, reply_markup=None):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text,
                  "parse_mode": "HTML"}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self.call("editMessageText", **params)

    def answer_callback(self, callback_id, text=None):
        params = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
        return self.call("answerCallbackQuery", **params)

    def download(self, file_id):
        """Содержимое файла по file_id; None — не скачался или больше 20 МБ."""
        info = self.call("getFile", file_id=file_id)
        if not info or not info.get("file_path"):
            return None
        if (info.get("file_size") or 0) > MAX_FILE_BYTES:
            return None
        try:
            resp = requests.get(
                f"{API}/file/bot{self.token}/{info['file_path']}", timeout=60)
            resp.raise_for_status()
        except Exception:  # noqa: BLE001
            _logger.exception("Телеграм: файл %s не скачан", file_id)
            return None
        return resp.content
