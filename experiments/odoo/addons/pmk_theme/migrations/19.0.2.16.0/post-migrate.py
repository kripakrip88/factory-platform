# -*- coding: utf-8 -*-
"""Задача 262: уже загруженные фото сотрудников — в аватары их пользователей.

До этой версии фото сотрудника в аватар пользователя не переносилось, и в
документах вместо фото стояла буква (Голубенко — «В»). Переносим разово;
дальше переносит models/hr_avatar.py при каждой смене фото. Повторный запуск
ничего не меняет: где картинки уже совпадают, запись не трогается.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["hr.employee"].with_context(active_test=False).search([("user_id", "!=", False)])._pmk_push_avatar()
