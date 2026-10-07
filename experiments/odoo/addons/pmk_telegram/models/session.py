# -*- coding: utf-8 -*-
"""Где человек сейчас в диалоге с ботом — одна строка на чат."""
from odoo import fields, models

STATES = [
    ("idle", "Ничего не ждём"),
    ("await_stage", "Ждём этап"),
    ("await_content", "Ждём «что нужно»"),
    ("collecting", "Дописываем в сделку"),
]


class PmkTelegramSession(models.Model):
    _name = "pmk.telegram.session"
    _description = "Диалог с ботом в Телеграме"

    chat_id = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", ondelete="cascade")
    state = fields.Selection(STATES, default="idle", required=True)
    stage_id = fields.Many2one("crm.stage", ondelete="set null")
    lead_id = fields.Many2one("crm.lead", ondelete="set null")
    # Альбом из нескольких скриншотов приходит отдельными сообщениями с общим
    # media_group_id — отвечаем на альбом один раз, а не на каждую картинку.
    media_group_id = fields.Char()
    last_activity = fields.Datetime()

    _chat_uniq = models.Constraint("UNIQUE(chat_id)", "Один диалог на чат.")
