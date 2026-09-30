# -*- coding: utf-8 -*-
"""Шаг 31 разбора UX (30.09.2026): сделка и воронка — данные боевой базы.

Всё идемпотентно и ничего, что поменяли руками, не затирает (hooks.py):
  • сроки стадий: Заявка 1 день, Расчёт 2, КП отправлено 7 — только если 0;
  • штатные причины проигрыша — в архив, если ими не отмечена ни одна сделка
    (заводские шесть загрузил data/crm_lost_reason.xml);
  • «Откуда пришёл = Почта» у заявок из письма — только где пусто;
  • доход сделок с расчётом — из цены клиенту (сделка №12: 1 000 → 9 500 000);
  • пользователь admin: имя и подпись «Administrator» → «Антон Карнеев»,
    логин не меняется. Только здесь, не при установке: на новой базе имя
    владельца не угадать.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_deal.hooks import apply_factory_defaults, rename_admin


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    apply_factory_defaults(env)
    rename_admin(env)
