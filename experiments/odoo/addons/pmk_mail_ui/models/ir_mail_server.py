# -*- coding: utf-8 -*-
"""Копия исходящего письма в папку «Отправленные» на почтовом сервере.

Отправка по SMTP и подшивка копии в папку — разные вещи. SMTP только передаёт
письмо дальше; копию в «Отправленные» кладёт почтовый клиент отдельной командой
IMAP APPEND. Odoo про IMAP-папки ящика ничего не знает, поэтому всё, что она
отправляет — уведомления, рассылка прайсов, письма из карточек, — до сих пор
не попадало в ящик вообще. Снабженец видел отправленное только внутри Odoo,
а в телефоне и в почтовом клиенте — нет.

Здесь копия подшивается после успешной отправки.

Композер самого mail_client подшивает копию сам (`_append_to_sent`), поэтому
его вызовы помечены контекстом и пропускаются — иначе письмо легло бы дважды.
"""
import logging
import re

from odoo import api, models

_logger = logging.getLogger(__name__)

SKIP_FLAG = "pmk_no_sent_copy"
EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    def send_email(self, message, *args, **kwargs):
        result = super().send_email(message, *args, **kwargs)
        if not self.env.context.get(SKIP_FLAG):
            # Письмо уже доставлено. Неудача подшивки не должна выглядеть
            # как неудача отправки, поэтому ошибки только в лог.
            try:
                self._pmk_file_to_sent(message)
            except Exception as exc:                     # noqa: BLE001
                _logger.warning("Копия в «Отправленные» не подшита: %s", exc)
        return result

    # ------------------------------------------------------------------
    def _pmk_file_to_sent(self, message):
        """Положить письмо в папку «Отправленные» того ящика, от чьего имени оно ушло."""
        if "mail.client.account" not in self.env:
            return False                                  # почтовый модуль снят
        sender = self._pmk_sender_address(message)
        if not sender:
            return False

        account = self.env["mail.client.account"].sudo().search(
            [("email", "=ilike", sender)], limit=1)
        if not account:
            # Письмо ушло не от подключённого ящика — подшивать некуда,
            # и это нормальный случай, а не ошибка.
            return False

        folder = account.folder_ids.filtered(lambda f: f.role == "sent")[:1]
        if not folder:
            _logger.info("У ящика %s нет папки «Отправленные» — копия не подшита",
                         account.email)
            return False

        connection = None
        try:
            connection = account._open_connection()
            connection.append(folder.imap_path, message.as_bytes(), flags=("\\Seen",))
        finally:
            if connection:
                connection.close()
        _logger.info("Копия письма подшита в «Отправленные» ящика %s", account.email)
        return True

    @staticmethod
    def _pmk_sender_address(message):
        """Чистый адрес отправителя из заголовка письма."""
        raw = ""
        try:
            raw = message.get("From") or ""
        except Exception:                                 # noqa: BLE001
            return None
        found = EMAIL_RE.search(raw)
        return found.group(0).lower() if found else None


class MailClientCompose(models.Model):
    _inherit = "mail.client.compose"

    @api.model
    def send(self, compose_id, values=None):
        # Композер подшивает копию своими силами. Без этой пометки письмо,
        # написанное из самого модуля, легло бы в «Отправленные» дважды.
        return super(MailClientCompose, self.with_context(**{SKIP_FLAG: True})).send(
            compose_id, values)
