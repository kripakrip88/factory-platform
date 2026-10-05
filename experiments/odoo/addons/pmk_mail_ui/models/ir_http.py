# -*- coding: utf-8 -*-
"""Счётчик новых писем — со страницей (разбор удобства, шаг 41, Г12).

Первое число счётчика на пункте «Продажи → Почта» и во вкладке браузера
приходит вместе со страницей (session_info), без отдельного запроса при
загрузке. Дальше его обновляет static/src/js/mail_counter.js — по сигналу
синхронизации почты и после правок в почте.

Ключ ставится только внутреннему пользователю с правом читать почту: у
остальных его нет вовсе, и счётчик в браузере не запускается. Ошибка здесь
уронила бы загрузку всего веб-клиента, поэтому всё, что может отказать,
проверяется до запроса (models/mail_client_step41.py, pmk_mail_unread_count:
без прав — 0).
"""
from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        if (request and request.session.uid and self.env.user._is_internal()
                and self.env["mail.client.account"].has_access("read")):
            info["pmk_mail_unread"] = self.env["mail.client.account"].pmk_mail_unread_count()
        return info
