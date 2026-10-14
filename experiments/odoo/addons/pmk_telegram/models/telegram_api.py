# -*- coding: utf-8 -*-
"""Тонкий клиент Bot API: только те вызовы, что нужны боту.

Без ORM — чтобы тесты подменяли его целиком (bot._pmk_api) и не ходили в сеть.
Ошибка Телеграма не роняет обработку: вызов пишет её в журнал и возвращает
None. Сделка важнее ответа бота — если ответ не дошёл, запись в Odoo остаётся.
"""
import json
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

    def call_files(self, method, files, **params):
        """Вызов с загрузкой файлов (multipart): files = {поле: (имя, байты)}.

        Вложенные структуры (reply_markup, media) Телеграм в multipart ждёт
        строкой JSON.
        """
        data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                for k, v in params.items() if v is not None}
        try:
            resp = requests.post(f"{API}/bot{self.token}/{method}", data=data,
                                 files=files, timeout=60)
            res = resp.json()
        except Exception:  # noqa: BLE001
            _logger.exception("Телеграм: %s не выполнен", method)
            return None
        if not res.get("ok"):
            _logger.warning("Телеграм: %s → %s", method, res.get("description"))
            return None
        return res.get("result")

    def send_photo(self, chat_id, photo, caption=None, reply_markup=None, thread_id=None):
        """photo — (имя, байты) для загрузки или file_id уже загруженной картинки."""
        params = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML",
                  "reply_markup": reply_markup,
                  "message_thread_id": int(thread_id) if thread_id else None}
        if isinstance(photo, tuple):
            return self.call_files("sendPhoto", {"photo": photo}, **params)
        params["photo"] = photo
        return self.call("sendPhoto", **{k: v for k, v in params.items() if v is not None})

    def edit_photo(self, chat_id, message_id, photo, caption=None, reply_markup=None):
        """Заменить картинку (и подпись, кнопки) в отправленном сообщении."""
        media = {"type": "photo", "caption": caption, "parse_mode": "HTML"}
        params = {"chat_id": chat_id, "message_id": message_id,
                  "reply_markup": reply_markup}
        if isinstance(photo, tuple):
            media["media"] = "attach://slide"
            return self.call_files("editMessageMedia", {"slide": photo},
                                   media=media, **params)
        media["media"] = photo
        return self.call("editMessageMedia", media=media,
                         **{k: v for k, v in params.items() if v is not None})

    def send(self, chat_id, text, reply_markup=None, thread_id=None):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if reply_markup:
            params["reply_markup"] = reply_markup
        # Тема (комната) группы с темами; без неё — «Общая».
        if thread_id:
            params["message_thread_id"] = int(thread_id)
        return self.call("sendMessage", **params)

    def edit(self, chat_id, message_id, text, reply_markup=None):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text,
                  "parse_mode": "HTML"}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self.call("editMessageText", **params)

    def leave_chat(self, chat_id):
        return self.call("leaveChat", chat_id=chat_id)

    @property
    def bot_id(self):
        """ID бота — число до двоеточия в токене (так его выдаёт @BotFather)."""
        try:
            return int(str(self.token).split(":", 1)[0])
        except ValueError:
            return None

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
