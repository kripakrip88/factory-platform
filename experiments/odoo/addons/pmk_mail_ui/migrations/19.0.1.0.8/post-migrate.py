# -*- coding: utf-8 -*-
"""Письма на info@ больше не создают лиды сами (разбор UX, шаг 53, 07.10.2026).

Решение Антона на вопрос приёмки шага 27 («на адрес info@ ещё настроен приём
писем в лиды… Выключить так же?») — «да». Боевая база, SELECT 07.10.2026:
mail_alias id 2, имя «info», модель crm.lead, команда «Продажи», умолчания
{'type': 'lead', 'team_id': 1}. Лид рождается кнопкой «Лид» в почте.

Что и почему — models/mail_client_step53.py (pmk_switch_off_lead_aliases).
Повторный запуск ничего не меняет. Вернуть — вписать имя «info» приёмнику
(Настройки → Технический → Псевдонимы). Приёмники счетов sales@ и
purchases@ (account.move) не трогаются.
"""
import logging

from odoo import api
from odoo.orm.utils import SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    off = env["mail.alias"]._pmk_switch_off_lead_aliases()
    _logger.info("pmk_mail_ui 19.0.1.0.8: выключено приёмников «письмо → лид»: %s %s",
                 len(off), off)
