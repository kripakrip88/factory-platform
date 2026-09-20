# -*- coding: utf-8 -*-
"""Настройка расписания рассылки при установке.

`nextcall` у задания хранится в UTC. Понедельник 09:10 по Владивостоку — это
воскресенье 23:10 UTC, и записывать такую дату прямо в XML значило бы зашить
разницу часовых поясов туда, где её никто не заметит при переезде сервера.
Поэтому считаем на месте.
"""
import datetime
import logging

import pytz

_logger = logging.getLogger(__name__)

TZ = "Asia/Vladivostok"      # площадка завода
HOUR, MINUTE = 9, 10
MONDAY = 0


def _next_monday_utc():
    tz = pytz.timezone(TZ)
    now = datetime.datetime.now(tz)
    ahead = (MONDAY - now.weekday()) % 7
    target = now + datetime.timedelta(days=ahead)
    local = tz.localize(datetime.datetime(
        target.year, target.month, target.day, HOUR, MINUTE))
    if local <= now:                       # сегодня понедельник, но время прошло
        local += datetime.timedelta(days=7)
    return local.astimezone(pytz.UTC).replace(tzinfo=None)


def post_init_hook(env):
    cron = env.ref("pmk_purchase.cron_price_request", raise_if_not_found=False)
    if not cron:
        return
    nextcall = _next_monday_utc()
    cron.sudo().write({"nextcall": nextcall})
    _logger.info("Рассылка прайсов: следующий прогон %s UTC (понедельник %s:%02d %s)",
                 nextcall, HOUR, MINUTE, TZ)
