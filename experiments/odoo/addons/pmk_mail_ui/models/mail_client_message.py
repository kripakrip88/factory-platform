# -*- coding: utf-8 -*-
"""Создание лида CRM из письма.

Главное требование к этому коду — лид из кнопки не должен отличаться от лида,
который создаёт почтовый алиас `zakaz@`. Иначе в воронке заведутся два сорта
лидов с разным заполнением, и любой отчёт по ним начнёт врать.

Поэтому здесь повторён путь ядра (`crm.lead.message_new` + `message_post`), а
не написан свой: те же три поля при создании, то же письмо в чате тем же
подтипом, те же вложения парами (имя, байты).
"""

import base64
import logging

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    # ondelete='set null', а не cascade и не restrict: удалённый лид не должен
    # ни утаскивать за собой письмо, ни мешать его удалить. После удаления лида
    # кнопка честно создаст новый.
    pmk_lead_id = fields.Many2one(
        "crm.lead",
        string="Лид",
        readonly=True,
        copy=False,
        ondelete="set null",
        index="btree_not_null",
    )

    # ------------------------------------------------------------------
    # кнопка
    # ------------------------------------------------------------------
    def action_pmk_create_lead(self):
        """Создать лид из письма либо открыть уже созданный."""
        self.ensure_one()
        self.check_access("read")

        lead = self._pmk_find_lead()
        created = not lead
        if created:
            lead = self._pmk_create_lead()

        # sudo точечно на одно наше поле: у зрителя общего ящика прав на запись
        # в письмо нет, а проверки на чтение письма и на создание лида уже
        # прошли выше. Тем же приёмом пользуется и сам почтовый модуль.
        if self.pmk_lead_id != lead:
            self.sudo().pmk_lead_id = lead.id

        return {
            "created": created,
            "action": {
                "type": "ir.actions.act_window",
                "name": _("Лид"),
                "res_model": "crm.lead",
                "res_id": lead.id,
                "views": [[False, "form"]],
                # Диалог, а не переход: у почтового модуля нет сохранения
                # состояния, и возврат по хлебным крошкам пересоздал бы его —
                # человек вернулся бы в первую папку и потерял открытое письмо.
                "target": "new",
            },
        }

    # ------------------------------------------------------------------
    # внутреннее
    # ------------------------------------------------------------------
    def _pmk_find_lead(self):
        """Лид, уже сделанный из этого письма — кнопкой или алиасом."""
        self.ensure_one()
        if self.pmk_lead_id:
            return self.pmk_lead_id
        if not self.message_id:
            return self.env["crm.lead"]

        # Алиас кладёт письмо в чат лида с тем же заголовком Message-ID, что
        # хранит почтовый модуль. Это единственный способ не сделать второй лид
        # к письму, которое уже приехало на zakaz@ и лид себе уже завело.
        posted = self.env["mail.message"].sudo().search(
            [
                ("message_id", "=", self.message_id),
                ("model", "=", "crm.lead"),
                ("res_id", "!=", False),
            ],
            limit=1,
        )
        if not posted:
            return self.env["crm.lead"]
        return self.env["crm.lead"].browse(posted.res_id).exists()

    def _pmk_create_lead(self):
        self.ensure_one()
        attachments, failed = self._pmk_letter_attachments()

        # `type` не передаём намеренно: у crm.lead он вычисляется от того,
        # включён ли в настройках CRM отдельный этап «Лиды». Жёсткое значение
        # разошлось бы с лидами из алиаса и сломалось бы в день, когда Антон
        # этот этап включит.
        #
        # `partner_id` берём готовый: почтовый модуль ищет контакт по адресу и
        # НЕ создаёт его, если не нашёл. Так же ведёт себя и почтовый шлюз
        # ядра. Автосоздание контакта здесь было бы вредно: ящик собирает
        # рассылки, и каждый промах кнопки оседал бы мусором в базе клиентов.
        lead = (
            self.env["crm.lead"]
            .with_context(
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                default_user_id=False,
            )
            .create(
                {
                    "name": self.subject or _("Без темы"),
                    "email_from": self.email_from,
                    "partner_id": self.partner_id.id or False,
                }
            )
        )
        lead._assign_userless_lead_in_team(_("письмо из почты"))

        lead.message_post(
            # Именно _display_body(), а не body_html: поле хранит письмо без
            # санитизации атрибутов, а вырезание удалённых картинок и
            # трекинг-пикселей модуль делает на отдаче. Иначе мы бы протащили
            # в CRM ровно то, от чего почта защищается.
            body=Markup(self._display_body() or ""),
            subject=self.subject,
            message_type="email",
            subtype_id=self.env.ref("crm.mt_lead_create").id,
            # False, а не None: при None ядро подставит текущего пользователя,
            # и письмо в чате будет выглядеть написанным менеджером.
            author_id=self.partner_id.id or False,
            email_from=self.email_from,
            date=self.date,
            # Без Message-ID ломается единственный надёжный способ связать это
            # письмо с лидом, который мог создать алиас.
            message_id=self.message_id,
            attachments=attachments,
            # Пустой список намеренно: получатели здесь означали бы рассылку
            # уведомлений — кнопка не должна писать отправителю.
            partner_ids=[],
        )

        if failed:
            items = Markup("").join(Markup("<li>%s</li>") % name for name, _err in failed)
            lead.message_post(
                body=Markup("<p>Не удалось забрать из почты:</p><ul>%s</ul>") % items,
                message_type="comment",
                subtype_xmlid="mail.mt_note",
            )
        return lead

    def _pmk_letter_attachments(self):
        """Пары (имя, байты) по каждой части письма.

        Возвращает ещё и список несработавших: одна недоступная часть не повод
        потерять лид целиком.
        """
        self.ensure_one()
        payload, failed = [], []

        # Строки частей появляются только при разборе тела. Синхронизация папки
        # выставляет has_attachment, но частей не создаёт — на непрочитанном
        # письме без этого вызова лид молча вышел бы без вложений.
        try:
            self.sudo()._fetch_body()
        except (UserError, OSError) as exc:
            _logger.warning("Письмо %s: тело не забрать — %s", self.id, exc)
            failed.append((_("тело письма"), str(exc)))

        for part in self.client_attachment_ids:
            try:
                # sudo обязателен: у пользователя почты на модель вложений
                # право только на чтение, а _fetch пишет результат скачивания.
                # Так же делает сам модуль в своём download().
                attachment = part.sudo()._fetch()
            except (UserError, OSError) as exc:
                # Ловим поштучно и не даём исключению всплыть: иначе Odoo
                # откатит транзакцию вместе с уже созданным лидом, а отметка
                # о неудаче на части не сохранится.
                failed.append((part.name, str(exc)))
                continue
            payload.append((part.name, base64.b64decode(attachment.datas)))

        return payload, failed
