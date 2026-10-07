# -*- coding: utf-8 -*-
"""Адрес, на который Телеграм присылает сообщения боту.

Чужой запрос отсекается секретом: Телеграм кладёт его в заголовок
X-Telegram-Bot-Api-Secret-Token (задаётся в pmk_setup_webhook). Без секрета
любой мог бы создавать сделки, подделав сообщение.

Ответ — всегда 200: иначе Телеграм повторяет то же сообщение снова и снова,
и одна сбойная картинка заблокировала бы бота. Ошибка откатывает только своё
сообщение (savepoint) и уходит в журнал, человеку — короткое «не получилось».
"""
import hmac
import json
import logging

from odoo import http
from odoo.http import Response, request, route

from ..models.bot import PARAM_SECRET, WEBHOOK_PATH

_logger = logging.getLogger(__name__)


class PmkTelegramController(http.Controller):

    @route(WEBHOOK_PATH, type="http", auth="public", methods=["POST"],
           csrf=False, save_session=False)
    def pmk_telegram_webhook(self, **_kw):
        env = request.env
        secret = env["ir.config_parameter"].sudo().get_param(PARAM_SECRET) or ""
        got = request.httprequest.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secret or not hmac.compare_digest(secret, got):
            return Response("forbidden", status=403)
        try:
            update = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return Response("ok")
        bot = env["pmk.telegram.bot"].sudo()
        try:
            with env.cr.savepoint():
                bot.pmk_handle_update(update)
        except Exception:  # noqa: BLE001 — см. шапку
            _logger.exception("Телеграм: сообщение %s не обработано",
                              update.get("update_id"))
            chat = ((update.get("message") or {}).get("chat")
                    or ((update.get("callback_query") or {}).get("message") or {}).get("chat")
                    or {})
            api_ = bot._pmk_api()
            if api_ and chat.get("id"):
                api_.send(chat["id"], "Не получилось записать — попробуйте ещё "
                                      "раз. Если повторится, скажите Claude.")
        return Response("ok")
