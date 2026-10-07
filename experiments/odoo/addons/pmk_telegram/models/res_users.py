# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # Char, а не Integer: ID в Телеграме бывают больше 2^31, а Integer в
    # Odoo — int4.
    pmk_telegram_id = fields.Char(
        "Telegram ID", copy=False, index=True,
        help="Числовой ID в Телеграме. Заполнен — бот принимает от этого "
             "человека сделки и создаёт их от его имени. ID бот сам "
             "показывает в ответ на /start тому, у кого нет доступа.")

    _pmk_telegram_id_uniq = models.Constraint(
        "UNIQUE(pmk_telegram_id)",
        "Этот Telegram ID уже привязан к другому пользователю.",
    )
