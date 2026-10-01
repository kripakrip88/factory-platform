# -*- coding: utf-8 -*-
"""Лиды из почты, заведённые до шага 27: название без «RE:», адрес без
имени, имя — в «Имя контакта» (разбор UX, шаг 27, 02.10.2026).

С этой версии кнопка «Лид» разбирает письмо сама (tools/lead_text.py,
models/mail_client_message.py, _pmk_create_lead). Здесь — те лиды, что
заведены раньше, по тем же правилам (lead_text.cleanup_values).

ЧТО ТРОГАЕМ. Только лиды (type = 'lead'), архивные тоже. Сделки — нет: их
названия правят руками, а «Эл. почта» сделки в списке и так в ⚙ (шаг 25).
У лида меняется:
  • название — только если начинается с «RE:», «FW:», «Fwd:», «:» и т. п.;
  • «Эл. почта» — только если в ней «Имя <адрес>»: остаётся адрес;
  • «Имя контакта» — только если пусто, контакта-человека у лида нет, а имя
    в «Эл. почте» не нашего ящика (пересылка коллеги — не клиент).
ИДЕМПОТЕНТНО: повторный запуск ничего не находит.

ИМЯ — В НАПИСАНИИ ИЗ «ПОЧТЫ». Лиды 5–11 завёл алиас ядра (до 28.09), и у
трёх из них имя раскодировано с пробелом на стыке кусков заголовка
(«Сергеев ич»). Те же письма в «Почте» раскодированы верно — если буквы
совпадают и отличие только в пробелах, берём написание оттуда
(lead_text.better_spelling).

КАРТОЧКУ КОНТАКТА НЕ ТРОГАЕМ. У «Эл. почты» лида в Odoo 19 есть обратная
запись (crm.lead._inverse_email_from): адрес, который отличается от почты
привязанного контакта, ядро переписывает в карточку контакта. Поэтому у
лида с контактом, почта которого другая, «Эл. почту» не правим. На боевой
базе 02.10.2026 контакта нет ни у одного лида.

На боевой базе 02.10.2026 — 13 лидов (6 активных), правка у 12; список с
«было → стало» — docs/disabled-features.md, раздел шага 27, и журнал
сервера (строка на каждый лид).

БЕЗ ОТМЕТОК В ЛЕНТЕ (tracking_disable): «Эл. почта» и «Имя контакта» у лида
отслеживаются, и миграция написала бы в ленту каждого лида от имени
OdooBot. Правка служебная — след в журнале сервера и в реестре.
"""
import logging

from odoo import api
from odoo.orm.utils import SUPERUSER_ID
from odoo.tools import email_normalize

from odoo.addons.pmk_mail_ui.tools import lead_text

_logger = logging.getLogger(__name__)


def _letter_names(env, address):
    """Имена отправителя из писем «Почты» с тем же адресом, свежие первыми."""
    names = []
    letters = env["mail.client.message"].search(
        [("email_from", "ilike", address)], order="date desc, id desc", limit=50)
    for letter in letters:
        name, letter_address = lead_text.split_sender(letter.email_from)
        if name and letter_address.lower() == address.lower() and name not in names:
            names.append(name)
    return names


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    own = env["mail.client.message"]._pmk_own_addresses()
    leads = env["crm.lead"].with_context(active_test=False).search(
        [("type", "=", "lead")], order="id")
    changed = 0
    for lead in leads:
        has_person = bool(lead.partner_id) and not lead.partner_id.is_company
        values = lead_text.cleanup_values(
            lead.name, lead.email_from, lead.contact_name, has_person, own)
        if "email_from" in values and lead.partner_id and \
                email_normalize(lead.partner_id.email or "") != email_normalize(values["email_from"]):
            # Ядро переписало бы этот адрес в карточку контакта.
            del values["email_from"]
        if values.get("contact_name"):
            _sender, address = lead_text.split_sender(lead.email_from)
            values["contact_name"] = lead_text.better_spelling(
                values["contact_name"], _letter_names(env, address))
        if not values:
            continue
        before = {fname: lead[fname] for fname in values}
        lead.with_context(tracking_disable=True, mail_notrack=True).write(values)
        changed += 1
        _logger.info("pmk_mail_ui 19.0.1.0.6: лид %s — было %s, стало %s",
                     lead.id, before, values)
    _logger.info("pmk_mail_ui 19.0.1.0.6: лидов %s, поправлено %s", len(leads), changed)
