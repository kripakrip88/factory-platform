# -*- coding: utf-8 -*-
"""Окно письма «Отправить КП» (разбор UX, шаг 33).

Это штатное окно письма Odoo; здесь — только то, что нужно окну КП. Всё
работает лишь при флаге контекста pmk_kp_send (его ставит кнопка расчёта):
то же окно из ленты любого документа ведёт себя как раньше.

АВТОР ПИСЬМА. Ядро ищет автора по адресу отправителя
(_compute_authorship → _message_compute_author). Адрес pmkpark@mail.ru в
базе есть только у контрагента самой организации («ИП Чулков В.В.»), и без
правки автором письма в ленте стала бы организация, а пользователь —
подписчиком, которому ушло бы уведомление на пустой адрес (у admin почты
нет; «красный конверт»). Автор — тот, кто отправляет.
"""

from odoo import api, fields, models
from odoo.tools.mail import email_split_tuples

from ..tools import spec_text
from .kp_send import KP_SEND_FLAG

SPEC_MODEL = "pmk.metal.spec"


class MailComposeMessageKp(models.TransientModel):
    _inherit = "mail.compose.message"

    # Строка над «Кому»: кто отправляет (серым — справка) и жёлтые плашки —
    # нет адреса отправителя, что не попадёт в КП или КП пустое, нет PDF,
    # кого вписать. Плашки ничего не запрещают.
    pmk_kp_sender_text = fields.Char(compute="_compute_pmk_kp_texts")
    pmk_kp_sender_hint = fields.Char(compute="_compute_pmk_kp_texts")
    pmk_kp_skip_text = fields.Char(compute="_compute_pmk_kp_texts")
    pmk_kp_pdf_hint = fields.Char(compute="_compute_pmk_kp_texts")
    pmk_kp_to_hint = fields.Char(compute="_compute_pmk_kp_texts")

    def _pmk_kp_spec(self):
        """Расчёт, из которого открыто окно «Отправить КП», или пусто."""
        self.ensure_one()
        if (not self.env.context.get(KP_SEND_FLAG) or self.model != SPEC_MODEL
                or self.composition_mode != "comment" or self.composition_batch):
            return self.env[SPEC_MODEL]
        return self.env[SPEC_MODEL].browse(self._evaluate_res_ids()[:1]).exists()

    @api.depends("model", "res_ids", "composition_mode", "email_from", "partner_ids",
                 "attachment_ids")
    @api.depends_context(KP_SEND_FLAG)
    def _compute_pmk_kp_texts(self):
        for composer in self:
            spec = composer._pmk_kp_spec()
            if not spec:
                composer.pmk_kp_sender_text = False
                composer.pmk_kp_sender_hint = False
                composer.pmk_kp_skip_text = False
                composer.pmk_kp_pdf_hint = False
                composer.pmk_kp_to_hint = False
                continue
            name, email = (email_split_tuples(composer.email_from or "") or [("", "")])[0]
            composer.pmk_kp_sender_text = spec_text.kp_sender_text(name, email)
            composer.pmk_kp_sender_hint = spec_text.kp_sender_hint(email)
            # Ни одного изделия с ценой — КП пустое; иначе тот же текст, что
            # в шапке расчёта рядом с «КП (PDF)». Условие то же, что у печати.
            if spec.product_ids.filtered("price_customer_unit"):
                composer.pmk_kp_skip_text = spec.kp_skip_text or False
            else:
                composer.pmk_kp_skip_text = spec_text.kp_empty_text(len(spec.product_ids))
            composer.pmk_kp_pdf_hint = (
                False if spec._pmk_kp_pdf(composer.attachment_ids) else spec_text.KP_NO_PDF)
            composer.pmk_kp_to_hint = False if composer.partner_ids else spec_text.kp_to_hint(
                bool(spec.partner_id),
                bool((spec.contact_id | spec.partner_id).filtered("email")))

    def _compute_authorship(self):
        super()._compute_authorship()
        for composer in self:
            spec = composer._pmk_kp_spec()
            if not spec:
                continue
            # Шаблона нет (удалили в Настройках) — ядро взяло бы почту
            # пользователя, а у admin она пуста. Отправитель тот же, что в
            # шаблоне: имя пользователя и ящик организации.
            if not composer.template_id.email_from and spec.pmk_kp_email_from:
                composer.email_from = spec.pmk_kp_email_from
            composer.author_id = self.env.user.partner_id
