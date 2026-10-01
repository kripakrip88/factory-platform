# -*- coding: utf-8 -*-
"""История расчётов и доборок по-русски (разбор UX, шаг 30, 02.10.2026).

Что и почему — pmk_calc/tools/tracking_ru.py. Правим только записи модуля
tracking_manager: отметки в ленте (message_type = 'notification') с его
подписями «New :», «Delete :», «Change :» или служебными ссылками на строки, и
значения отслеживания со ссылками на позиции доборки. Через SQL: это
история, пересчитывать в ней нечего. Повторный запуск ничего не меняет.

Боевая база, 02.10.2026 (SELECT): 24 сообщения — расчёты СМ-00016, СМ-00021…
СМ-00025 (17), доборки ДОБ-00001, ДОБ-00007, ДОБ-00009, ДОБ-00012 (7); и
значение отслеживания 107 (ДОБ-00001, поле «Доборки»). Было и стало, как
вернуть — docs/disabled-features.md, шаг 30.

Доводка: запись ядра о создании наших документов «… created» →
«Создано: …» (как пишет ядро по-русски). Только модели pmk.*: на боевой базе
8 записей — расчёты СМ-00015, СМ-00021, СМ-00022 и удалённый расчёт id 1
(сообщения 241, 262, 265, 239), доборки ДОБ-00001, ДОБ-00005 (240, 246),
РК-00001 (281), ЛР-00001 (2078). Английские записи о создании товаров и
контрагентов («Product created» и др.) — не наши документы, вне шага.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_calc.tools.tracking_ru import (
    CREATED, created_ru, dobor_ids, rewrite, titles_from_history)

_logger = logging.getLogger(__name__)

PATTERNS = ["%<b>New :</b>%", "%<b>Delete :</b>%", "%<b>Change :</b>%",
            "%pmk.metal.spec.line(%", "%pmk.dobor.order.line,%"]


def migrate(cr, version):
    cr.execute(
        "SELECT id, body FROM mail_message WHERE message_type = 'notification' AND ("
        + " OR ".join(["body LIKE %s"] * len(PATTERNS)) + ") ORDER BY id",
        PATTERNS)
    messages = cr.fetchall()
    cr.execute("""SELECT id, old_value_char, new_value_char FROM mail_tracking_value
                   WHERE old_value_char LIKE %s OR new_value_char LIKE %s ORDER BY id""",
               ["%pmk.dobor.order.line,%"] * 2)
    values = cr.fetchall()

    # Названия позиций: живые — из таблицы, удалённые — из той же истории
    # («Название доборки : → Доборка 2»), иначе слово «доборка».
    ids = set()
    for _id, body in messages:
        ids |= dobor_ids(body)
    for _id, old, new in values:
        ids |= dobor_ids(old) | dobor_ids(new)
    titles = titles_from_history(body for _id, body in messages)
    if ids:
        cr.execute("SELECT id, title FROM pmk_dobor_order_line WHERE id = ANY(%s)", [list(ids)])
        titles.update({line_id: title for line_id, title in cr.fetchall() if (title or "").strip()})

    for message_id, body in messages:
        new_body = rewrite(body, titles)
        if new_body != body:
            cr.execute("UPDATE mail_message SET body = %s WHERE id = %s", [new_body, message_id])
            _logger.info("Шаг 30: история по-русски, mail_message %s", message_id)
    for value_id, old, new in values:
        old2, new2 = rewrite(old, titles, html=False), rewrite(new, titles, html=False)
        if (old2, new2) != (old, new):
            cr.execute("UPDATE mail_tracking_value SET old_value_char = %s, new_value_char = %s"
                       " WHERE id = %s", [old2, new2, value_id])
            _logger.info("Шаг 30: значение отслеживания %s — названия позиций доборки", value_id)

    # Запись ядра о создании наших документов — по-русски.
    cr.execute("""SELECT id, body FROM mail_message
                   WHERE message_type = 'notification' AND model LIKE %s AND body ~ %s
                   ORDER BY id""", ["pmk.%", CREATED.pattern])
    for message_id, body in cr.fetchall():
        new_body = created_ru(body)
        if new_body != body:
            cr.execute("UPDATE mail_message SET body = %s WHERE id = %s", [new_body, message_id])
            _logger.info("Шаг 30: «Создано:» по-русски, mail_message %s", message_id)

    # Перевод подписей шаблона живёт у вендора (vendor/tracking_manager/
    # i18n_extra/ru.po, правило vendor/README.md) и попадает в базу при
    # I18N=1 sh deploy.sh. Здесь его только дочитываем — на случай выкладки
    # без I18N=1: иначе новые записи истории остались бы английскими.
    env = api.Environment(cr, SUPERUSER_ID, {})
    langs = [code for code, _name in env["res.lang"].get_installed() if code != "en_US"]
    if langs and env["ir.module.module"]._get("tracking_manager").state == "installed":
        env["ir.module.module"]._load_module_terms(["tracking_manager"], langs, overwrite=True)
        _logger.info("Шаг 30: перевод tracking_manager дочитан (%s)", ", ".join(langs))
