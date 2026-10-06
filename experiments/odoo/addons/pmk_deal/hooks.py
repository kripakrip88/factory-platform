# -*- coding: utf-8 -*-
"""Заводские настройки сделки (разбор UX, шаг 31, 30.09.2026).

Вызываются из миграции 19.0.1.0.4 (боевая база) и при установке модуля
(новая база — так же, как боевая). Каждая функция идемпотентна и не трогает
того, что уже поменяли руками.

ПОЧЕМУ НЕ DATA-ФАЙЛ. Стадии, штатные причины проигрыша и администратор
принадлежат чужим модулям (crm, base) и записаны с noupdate: data-файл их
либо пропустит, либо — без noupdate — будет затирать на каждом деплое то,
что Антон потом поправит сам в настройках.
"""

from markupsafe import Markup

from odoo.tools import SQL, html2plaintext
from odoo.tools.sql import column_exists

# Сколько дней сделка может стоять в стадии, пока не «зависла».
# Предложение разбора («Пороги сигналов»), утверждает Антон. Выиграно — без
# срока: сделка там не ждёт ответа.
STAGE_THRESHOLDS = [
    ("crm.stage_lead1", 1),  # Заявка: ответить в тот же день
    ("crm.stage_lead2", 2),  # Расчёт
    ("crm.stage_lead3", 7),  # КП отправлено: ждём решения клиента
]

# Штатные причины проигрыша — архивируются, когда есть заводские.
STOCK_LOST_REASONS = ["crm.lost_reason_1", "crm.lost_reason_2", "crm.lost_reason_3"]
FACTORY_LOST_REASON = "pmk_deal.lost_reason_price"

ADMIN_OLD_NAME = "Administrator"
ADMIN_NEW_NAME = "Антон Карнеев"

# Значения в старой истории сделки — словами завода (разбор UX, шаг 39).
# Поле → {записанное значение: наше}. Подписи этих списков с шага 39 —
# «В работе», «Проиграно», «Сделка» (pmk_theme/i18n_words/crm.po), а
# отслеживание хранит подпись текстом на момент изменения: скрипты без языка
# писали «Pending → Lost», люди — «Ожидает → Выиграно», «Лид → Возможность».
TRACKING_WORDS = {
    "won_status": {
        "Pending": "В работе", "Ожидает": "В работе",
        "Lost": "Проиграно", "Потерян": "Проиграно",
        "Won": "Выиграно",
    },
    "type": {"Opportunity": "Сделка", "Возможность": "Сделка", "Lead": "Лид"},
}


def post_init_hook(env):
    apply_factory_defaults(env)
    number_active_deals(env)


def apply_factory_defaults(env):
    set_stage_thresholds(env)
    archive_stock_lost_reasons(env)
    backfill_source(env)
    recompute_deal_money(env)


def set_stage_thresholds(env):
    """Срок стадии — только если он ещё не задан (0 = «не следить»).

    С этим числом ядро Odoo 19 само рисует «зависшую» сделку: плашка на
    кнопке стадии, счётчик в шапке колонки воронки, фильтр «Зависшие». Наше
    добавлено только «N дн» в списке и на карточке (виды pmk_deal). Это
    сигнал: переход по стадиям ничем не ограничен.
    """
    for xmlid, days in STAGE_THRESHOLDS:
        stage = env.ref(xmlid, raise_if_not_found=False)
        if stage and not stage.rotting_threshold_days:
            stage.rotting_threshold_days = days


def archive_stock_lost_reasons(env):
    """Штатные причины — в архив, если ни одна сделка ими не отмечена.

    Отмеченную не трогаем: в архиве она пропала бы из окна «Потерян», а у
    старой сделки осталась бы ссылкой на невидимую запись. Без заводских
    причин (data-файл не загрузился) ничего не архивируем: окно не должно
    остаться пустым.
    """
    if not env.ref(FACTORY_LOST_REASON, raise_if_not_found=False):
        return
    Lead = env["crm.lead"].with_context(active_test=False)
    for xmlid in STOCK_LOST_REASONS:
        reason = env.ref(xmlid, raise_if_not_found=False)
        if not reason or not reason.active:
            continue
        if Lead.search_count([("lost_reason_id", "=", reason.id)]):
            continue
        reason.active = False


def backfill_source(env):
    """«Откуда пришёл = Почта» у заявок, которые родились из письма.

    Два признака: лид сделан кнопкой «Лид» в почте (письмо помнит лид,
    pmk_lead_id модуля pmk_mail_ui) или первое сообщение в его ленте —
    входящее письмо (так заводил лиды приёмник zakaz@ до 28.09). Пустое
    поле не заполняем догадкой: ставим только «Почту» и только туда, где
    значения ещё нет. SQL, а не запись через ORM, — чтобы не сыпать в ленту
    каждой старой сделки строку истории.
    """
    cr = env.cr
    if column_exists(cr, "mail_client_message", "pmk_lead_id"):
        cr.execute("""
            UPDATE crm_lead l
               SET pmk_source = 'mail'
             WHERE l.pmk_source IS NULL
               AND EXISTS (SELECT 1 FROM mail_client_message m WHERE m.pmk_lead_id = l.id)
        """)
    cr.execute("""
        UPDATE crm_lead l
           SET pmk_source = 'mail'
         WHERE l.pmk_source IS NULL
           AND (SELECT m.message_type
                  FROM mail_message m
                 WHERE m.model = 'crm.lead' AND m.res_id = l.id
                 ORDER BY m.id
                 LIMIT 1) = 'email'
    """)
    env["crm.lead"].invalidate_model(["pmk_source"])


def recompute_deal_money(env):
    """Доход сделок, у которых есть расчёт, — из цены клиенту.

    Поле дохода было обычным и стало вычисляемым: Odoo сам пересчитывает
    только НОВЫЕ колонки, старую — нет. Без этого у сделки №12 так и стояли
    бы вписанные руками 1 000 ₽ вместо 9 500 000 ₽ из СМ-00024. Изменение
    попадёт в историю сделки — видно, откуда взялась сумма.
    """
    Lead = env["crm.lead"].with_context(active_test=False)
    leads = Lead.search([("spec_ids", "!=", False)])
    if not leads:
        return
    for fname in ("pmk_spec_id", "expected_revenue"):
        env.add_to_compute(Lead._fields[fname], leads)
    leads._recompute_recordset(["pmk_spec_id", "expected_revenue"])
    leads.flush_recordset(["pmk_spec_id", "expected_revenue"])


def rename_admin(env):
    """«Administrator» → «Антон Карнеев»; логин admin не меняется.

    Менеджер сделки и подпись писем клиенту были «Administrator» (подпись
    пользователя — «<div>Administrator</div>»). Только в боевой миграции:
    на новой базе имя владельца не угадать. Меняем, только если стоит
    штатное имя — переименованного руками не трогаем. Имя живёт у
    контрагента пользователя (base.partner_admin, noupdate): обновление base
    его не вернёт. Старые сообщения в истории подпишутся новым именем —
    автор хранится ссылкой, а не текстом.
    """
    user = env.ref("base.user_admin", raise_if_not_found=False)
    if not user:
        return
    if user.partner_id.name == ADMIN_OLD_NAME:
        user.partner_id.name = ADMIN_NEW_NAME
    if html2plaintext(user.signature or "").strip() == ADMIN_OLD_NAME:
        user.signature = Markup("<div>%s</div>") % ADMIN_NEW_NAME


def tracking_words_ru(env):
    """Старые значения «Выиграно/проиграно» и «Тип» в истории сделок — словами
    завода (шаг 39). Только точное совпадение со штатным словом (TRACKING_WORDS):
    повтор ничего не меняет, чужое значение не трогается. SQL — это история.
    Возвращает число исправленных значений.
    """
    cr = env.cr
    changed = 0
    for fname, words in TRACKING_WORDS.items():
        for column in ("old_value_char", "new_value_char"):
            for old, new in words.items():
                cr.execute(SQL(
                    "UPDATE mail_tracking_value t SET %(col)s = %(new)s"
                    "  FROM ir_model_fields f"
                    " WHERE f.id = t.field_id AND f.model = 'crm.lead' AND f.name = %(fname)s"
                    "   AND t.%(col)s = %(old)s",
                    col=SQL.identifier(column), new=new, fname=fname, old=old,
                ))
                changed += cr.rowcount
    if changed:
        env["mail.tracking.value"].invalidate_model(["old_value_char", "new_value_char"])
    return changed


def number_active_deals(env):
    """Номера «СД-» активным сделкам без номера (разбор UX, шаг 48).

    Решение Антона 06.10.2026: «присвоить всем сделкам активным, кроме
    архивных». Архивные (и проигранные — они тоже в архиве) остаются без
    номера, лиды — тоже. Порядок — по дню превращения в сделку
    (date_conversion, у созданной сразу сделкой — create_date), дата номера —
    тот же день по поясу менеджера сделки (models/deal_number.py). Повторный
    запуск ничего не меняет: у пронумерованных номер уже есть. Возвращает
    число выданных номеров.
    """
    deals = env["crm.lead"].search([
        ("type", "=", "opportunity"),
        ("pmk_number", "=", False),
    ])
    deals._pmk_assign_number()
    return len(deals.filtered("pmk_number"))
