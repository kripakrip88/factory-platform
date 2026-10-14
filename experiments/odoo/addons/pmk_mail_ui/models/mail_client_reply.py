# -*- coding: utf-8 -*-
"""Ответ и пересылка из Odoo (редизайн почты, шаг 6; доска №40; разбор Г3–Г7).

Из Odoo ещё не уходило ни одного письма, поэтому всё ниже всплыло бы с
первого ответа:

- Г3 «Ответить» на наше же письмо (из «Отправленных» или последнее в
  переписке) уходило самому себе: вендор берёт адрес отправителя. Для своего
  письма отвечаем тем, кому оно было адресовано.
- Г4 Письмо уходило от голого адреса. Имя отправителя — у ящика
  (pmk_sender_name), пусто — имя пользователя.
- Г5 Строка цитаты была по UTC и не по-русски: «2026-09-28 01:09:00».
  Теперь «28.09.2026, 11:09, Имя <адрес> пишет:» в поясе пользователя.
- Г6 «Переслать» не прикладывало вложения исходного письма — а чертёж
  клиента инженеру и есть главный случай пересылки на заводе.
- Г7 Автосохранение — в композере (composer.js), только в Odoo; в
  «Черновики» ящика — при закрытии (mail_client_compose.save_draft).
- Подпись — у каждого своя (Антон, 14.10.2026): нет общей подписи у ящика —
  подпись пользователя из его профиля («Мой профиль → Подпись»).
"""

import logging
import re

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import formataddr
from odoo.tools.mail import email_split_and_format

_logger = logging.getLogger(__name__)


class MailClientAccount(models.Model):
    _inherit = "mail.client.account"

    pmk_sender_name = fields.Char(
        "Имя отправителя",
        help="Как письма из Odoo подписаны у получателя: «Имя <адрес>». "
             "Пусто — имя пользователя, который отправляет.")


class MailClientSignature(models.Model):
    _inherit = "mail.client.signature"

    @api.model
    def _default_for(self, account, mode="new"):
        signature = super()._default_for(account, mode)
        if signature:
            return signature
        # У ящика есть общая подпись, но не для ответов — так и задумано,
        # подпись пользователя её не подменяет.
        if self.search_count([("account_id", "=", account.id), ("is_default", "=", True)]):
            return None
        body = self.env.user.signature or ""
        if not re.sub(r"<[^>]+>|&nbsp;|\s", "", str(body)):
            return None
        # Запись в памяти, в базу не пишется: подпись живёт в профиле.
        return self.new({"name": self.env.user.name, "account_id": account.id,
                         "body_html": body, "use_on_reply": True})

    def _as_block(self):
        self.ensure_one()
        if isinstance(self.id, int):
            return super()._as_block()
        return Markup('<div class="o_mail_client_signature" data-signature-id="user">'
                      '<p><br/></p>%s</div>') % Markup(self.body_html or "")


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    def _quote_header(self):
        self.ensure_one()
        sender = self.email_from or ""
        if not self.date:
            return "%s пишет:" % sender
        local = fields.Datetime.context_timestamp(self, self.date)
        return "%s, %s пишет:" % (local.strftime("%d.%m.%Y, %H:%M"), sender)


class MailClientCompose(models.Model):
    _inherit = "mail.client.compose"

    # ------------------------------------------------------------------
    # Г3: ответ на своё письмо
    # ------------------------------------------------------------------
    @api.model
    def _prepare_from_parent(self, parent, mode, account):
        values = super()._prepare_from_parent(parent, mode, account)
        # Своё письмо — в «Отправленных» или с адреса ящика (тот же признак,
        # что у строки списка «Кому: …» и у переписки).
        if mode in ("reply", "reply_all") and parent._is_outgoing():
            values["email_to"] = parent.email_to or ""
            if mode == "reply_all":
                own = (account.email or "").lower()
                values["email_cc"] = ", ".join(
                    address for address in email_split_and_format(parent.email_cc or "")
                    if not own or own not in address.lower())
        return values

    # ------------------------------------------------------------------
    # Г4: имя отправителя
    # ------------------------------------------------------------------
    def _pmk_sender_name(self):
        self.ensure_one()
        return ((self.account_id.pmk_sender_name or "").strip()
                or (self.user_id.name or "").strip())

    def _pmk_from(self):
        self.ensure_one()
        name = self._pmk_sender_name()
        email = self.account_id.email or ""
        return formataddr((name, email)) if name and email else email

    def _build_message(self, message_id=None):
        message = super()._build_message(message_id=message_id)
        sender = self._pmk_from()
        if sender and sender != (self.account_id.email or ""):
            message.replace_header("From", sender)
        return message

    def _to_payload(self):
        payload = super()._to_payload()
        name = self._pmk_sender_name()
        email = self.account_id.email or ""
        payload["pmk_from"] = "%s <%s>" % (name, email) if name else email
        payload["parent_id"] = self.parent_id.id or False
        return payload

    # ------------------------------------------------------------------
    # Г6: пересылка с вложениями
    # ------------------------------------------------------------------
    @api.model
    def start(self, account_id, mode="new", message_id=None):
        payload = super().start(account_id, mode=mode, message_id=message_id)
        if mode != "forward" or not message_id:
            return payload
        draft = self.browse(payload["id"])
        failed = draft._pmk_attach_parent_parts()
        payload = draft._to_payload()
        if failed:
            payload["pmk_forward_failed"] = failed
        return payload

    def _pmk_attach_parent_parts(self):
        """Скачать вложения исходного письма и приложить к пересылке.

        Картинки в тексте (подпись, логотип — pmk_inline) не прикладываем:
        их место в цитате, а не в списке вложений. Часть, которую сервер не
        отдал, пропускаем и называем в ответе — пересылка без одного файла
        лучше, чем никакой.
        """
        self.ensure_one()
        failed = []
        parts = self.parent_id.client_attachment_ids.filtered(lambda part: not part.pmk_inline)
        for part in parts:
            try:
                source = part.sudo()._fetch()
            except UserError as exc:
                _logger.info("Пересылка: вложение %s не скачано: %s", part.name, exc)
                failed.append(part.name)
                continue
            attachment = self.env["ir.attachment"].create({
                "name": source.name,
                "raw": source.sudo().raw,
                "mimetype": source.mimetype or "application/octet-stream",
                "res_model": self._name,
                "res_id": self.id,
            })
            self.attachment_ids = [fields.Command.link(attachment.id)]
        return failed
