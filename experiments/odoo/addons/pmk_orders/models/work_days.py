# -*- coding: utf-8 -*-
"""Рабочие дни для срока изготовления (шаг З-15) — чистые функции, без ORM.

«15 раб. дней с момента оплаты»: день оплаты не считается, отсчёт — со
следующего дня (как ст. 191 ГК РФ: срок начинается на следующий день после
события). Пятница + 1 рабочий день = понедельник.

Какие дни рабочие и какие праздники — решает вызывающий (project_task.py:
календарь рабочего времени компании, его «Общие выходные»). Здесь только
счёт.
"""
import datetime

WEEKDAYS = frozenset(range(5))  # пн–пт
# Предохранитель: календарь без единого рабочего дня или праздники сплошняком
# не должны вешать сохранение. Дальше этого — «не посчитали».
MAX_SPAN_DAYS = 3660


def add_work_days(start, days, workdays=WEEKDAYS, holidays=frozenset()):
    """Дата, когда истекают ``days`` рабочих дней от ``start``.

    ``start`` сам не считается. ``days`` <= 0 — вернёт ``start``. Нет ни
    одного рабочего дня недели — пн–пт. Не уложились в 10 лет — None.
    """
    if not start:
        return None
    if days <= 0:
        return start
    workdays = frozenset(workdays) or WEEKDAYS
    holidays = frozenset(holidays or ())
    current = start
    left = days
    for _step in range(MAX_SPAN_DAYS):
        current += datetime.timedelta(days=1)
        if current.weekday() in workdays and current not in holidays:
            left -= 1
            if not left:
                return current
    return None
