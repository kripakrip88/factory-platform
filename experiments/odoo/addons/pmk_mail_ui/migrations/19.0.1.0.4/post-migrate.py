# -*- coding: utf-8 -*-
"""pmkpark@mail.ru — в режим «Только чтение + общие отметки» (разбор UX, Г1).

Решение Антона 29.09.2026: «делаем общими». Прочитанное, отвеченное и флажок
теперь ходят между Odoo и mail.ru в обе стороны (models/mail_client_flags.py),
перенос и удаление из Odoo по-прежнему закрыты.

ЯЩИК ИЩЕМ ПО АДРЕСУ, а не по id=2: миграция должна работать и на копии базы.
Только из «только чтения»: если ящик уже переключили руками (в Настройках —
в любую сторону), решение человека не перебиваем.

zakaz@ остаётся «только чтение»: решение касалось pmkpark@mail.ru.

ОТМЕТКИ, ПОСТАВЛЕННЫЕ В ODOO ДО ЭТОЙ ПРАВКИ. До сих пор они на сервер не
уходили (is_dirty=True, очереди нет). Первый же проход новой синхронизации
прочитал бы отметки с mail.ru и стёр бы их: открытое письмо снова жирное,
«отвечено» (его ставит ответ из Odoo) и флажок пропадают. Поэтому всё, что
у такого письма СТОИТ, отдаём в очередь: первым делом прохода оно уйдёт на
mail.ru. По is_dirty не понять, какая из отметок менялась в Odoo, но это и
не нужно: «+FLAGS» ничего не портит — отметка, пришедшая с сервера, там уже
есть. Разве что вернётся флажок, снятый на mail.ru после 27.09 у письма,
которое трогали и в Odoo; это заметно и снимается одним щелчком.

Снятых отметок («непрочитано», «без флажка») НЕ отдаём: «-FLAGS» стёр бы
отметку, поставленную на mail.ru уже после 27.09, а у письма, которое в
Odoo только открыли, «не прочитано» значит «Odoo ещё не знает», а не «так
решил менеджер». «Непрочитано», нажатое в Odoo до выкладки, поэтому
потеряется; сколько таких писем, пишем в журнал. 29.09 (SELECT при доводке)
грязных писем 11, у всех только «прочитано», непрочитанных среди них нет.

ВНИМАНИЕ ДЛЯ КОПИИ БАЗЫ: миграция только ставит операции в очередь, сама на
сервер не ходит. Но первый проход крона на копии отправит очередь в
НАСТОЯЩИЙ ящик. Проверять на копии — с выключенными кронами и active_sync.
"""
import logging

from odoo import api
from odoo.orm.utils import SUPERUSER_ID

from odoo.addons.pmk_mail_ui.models.mail_client_flags import SHARED_FLAGS_MODE

_logger = logging.getLogger(__name__)

MAILBOX = "pmkpark@mail.ru"
# Поле письма → отметка IMAP. Те же три, что общие в новом режиме.
MARKS = (("flag_seen", "\\Seen"), ("flag_answered", "\\Answered"), ("flag_flagged", "\\Flagged"))


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    account = env["mail.client.account"].with_context(active_test=False).search([
        ("email", "=ilike", MAILBOX), ("sync_mode", "=", "one_way"),
    ], limit=1)
    if not account:
        return
    account.sync_mode = SHARED_FLAGS_MODE

    SyncOp = env["mail.client.sync.op"]
    touched = env["mail.client.message"].search([
        ("account_id", "=", account.id), ("is_dirty", "=", True),
    ])
    # Повторный запуск (или ручная отметка между) не должен ставить вторую
    # операцию на ту же отметку того же письма.
    queued = {
        (op.message_id.id, flag)
        for op in SyncOp.search([
            ("account_id", "=", account.id), ("state", "=", "pending"),
            ("op_type", "=", "set_flag"),
        ])
        for flag in (op.payload or {}).get("flags", [])
    }
    sent = 0
    for message in touched:
        flags = [flag for field, flag in MARKS
                 if message[field] and (message.id, flag) not in queued]
        if flags:
            # Одной операцией: STORE +FLAGS принимает список.
            SyncOp.queue(message, "set_flag", {"flags": flags})
            sent += len(flags)
    unread = len(touched.filtered(lambda m: not m.flag_seen))
    _logger.info(
        "pmk_mail_ui: ящик %s (id %s) — «только чтение + общие отметки»; "
        "в очередь на сервер отдано %s отметок у %s писем, тронутых в Odoo раньше; "
        "«непрочитано» не отправлено у %s писем",
        account.email, account.id, sent, len(touched), unread,
    )
