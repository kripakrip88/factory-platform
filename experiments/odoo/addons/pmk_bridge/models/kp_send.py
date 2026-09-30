# -*- coding: utf-8 -*-
"""Печать и отправка КП из расчёта (разбор UX, шаг 33).

ПОЧЕМУ ШТАТНОЕ ОКНО ПИСЬМА, А НЕ СВОЁ. Кнопка «Отправить КП» открывает то же
окно, что «Отправить по почте» у заказа Odoo (sale.action_quotation_send):
получатель, тема, текст и PDF уже подставлены, менеджер правит что нужно и
жмёт «Отправить». Кнопка сама ничего не шлёт — письмо уходит только из окна.

ОТ КОГО УХОДИТ ПИСЬМО — ГЛАВНАЯ ЛОВУШКА. Исходящий сервер Mail.ru принимает
письмо, только если адрес отправителя равен логину ящика (pmkpark@mail.ru).
Штатное окно берёт отправителя из почты пользователя, а у admin она пуста;
тогда ядро подставляет notifications@pmkpark.ru, этот адрес не подходит ни к
одному серверу, и письмо уходит через первый сервер по порядку — Mail.ru,
который его отвергает. Поэтому отправитель задан явно: имя того, кто
отправляет, и почта ОРГАНИЗАЦИИ расчёта — «Антон Карнеев <pmkpark@mail.ru>».
По этому адресу ядро (ir.mail_server._find_mail_server) само находит сервер
с тем же from_filter, и конверт MAIL FROM тоже будет ящиком завода.
Отдельное «Имя отправителя» у ящика — шаг 21; до него имя — пользователя.

ОТВЕТ КЛИЕНТА. Без явного Reply-To ядро в режиме «сообщение на документе»
ставит catchall@pmkpark.ru, а этот адрес никто не читает. Шаблон ставит
Reply-To = тот же ящик: ответ придёт в pmkpark@mail.ru и будет виден в «Почте».

ЧТО ПРОИСХОДИТ ПОСЛЕ «ОТПРАВИТЬ». Письмо с PDF ложится в ленту расчёта (так
работает штатное окно). Затем message_post ниже зовёт _pmk_kp_sent — точку
расширения: модуль сделки пишет заметку в ленту сделки и двигает её стадию
(pmk_deal/models/kp_sent.py). Приём тот же, что у sale (mark_so_as_sent):
флаг в контексте окна, и срабатывает он только на реальной отправке.
Письмо без PDF КП (вложение убрали в окне, шаблон удалён) — тоже письмо:
в окне об этом жёлтая плашка, а стадию сделки оно не двигает.
"""

from odoo import api, fields, models
from odoo.tools import email_normalize, formataddr

from ..tools import spec_text

# Флаг контекста окна «Отправить КП». Им помечены действие кнопки, само окно
# (mail_compose_message.py) и пост в ленту расчёта.
KP_SEND_FLAG = "pmk_kp_send"
KP_TEMPLATE = "pmk_bridge.mail_template_metal_spec_quotation"


class MetalSpecKpSend(models.Model):
    _inherit = "pmk.metal.spec"

    # ─── Письмо: всё без хранения, считается в момент открытия окна ────────
    #
    # Шаблон письма (data/mail_template_kp.xml) обращается только к этим
    # полям: в выражениях шаблона — пути к полям, без кода, и Антон может
    # править текст в Настройках, не рискуя сломать подстановки.
    pmk_kp_email_from = fields.Char(
        "Отправитель КП", compute="_compute_pmk_kp_sender",
        help="Имя того, кто отправляет, и почта организации расчёта. Сервер "
             "Mail.ru принимает письмо только с адреса своего ящика.")
    pmk_kp_sender_name = fields.Char("Кто отправляет", compute="_compute_pmk_kp_sender")
    pmk_kp_sender_phone = fields.Char("Телефон в подписи", compute="_compute_pmk_kp_sender")
    pmk_kp_sender_email = fields.Char("Почта в подписи", compute="_compute_pmk_kp_sender")
    pmk_kp_recipient_id = fields.Many2one(
        "res.partner", "Кому отправить КП", compute="_compute_pmk_kp_recipient",
        help="Контактное лицо, если у него есть почта, иначе клиент. Нет "
             "почты ни у кого — пусто: получателя впишут в окне письма.")
    pmk_kp_subject = fields.Char("Тема письма с КП", compute="_compute_pmk_kp_subject")
    pmk_kp_greeting = fields.Char("Приветствие", compute="_compute_pmk_kp_recipient")

    @api.depends("company_id.email", "company_id.phone")
    @api.depends_context("uid")
    def _compute_pmk_kp_sender(self):
        user = self.env.user
        for spec in self:
            address = email_normalize(spec.company_id.email) or email_normalize(user.email)
            spec.pmk_kp_email_from = formataddr((user.name or "", address)) if address else False
            spec.pmk_kp_sender_name = user.name or False
            spec.pmk_kp_sender_phone = user.partner_id.phone or spec.company_id.phone or False
            spec.pmk_kp_sender_email = address or False

    @api.depends("contact_id.email", "contact_id.name", "contact_id.is_company",
                 "partner_id.email", "partner_id.name", "partner_id.is_company")
    def _compute_pmk_kp_recipient(self):
        for spec in self:
            # Контакт без почты заранее не подставляем: у штатного окна тогда
            # гаснет «Отправить» (partner_ids_all_have_email), и человек
            # не поймёт почему.
            recipient = (spec.contact_id | spec.partner_id).filtered("email")[:1]
            spec.pmk_kp_recipient_id = recipient
            spec.pmk_kp_greeting = spec_text.kp_greeting(
                recipient.name, is_person=bool(recipient) and not recipient.is_company)

    @api.depends("name", "note")
    def _compute_pmk_kp_subject(self):
        for spec in self:
            spec.pmk_kp_subject = spec_text.kp_subject(spec.name, spec.note)

    def action_send_quotation(self):
        """Кнопка «Отправить КП»: открыть окно письма. Ничего не отправляет.

        Окно открывается всегда — без клиента, без почты, без цен: сигналы в
        окне показывают, чего не хватает, но не запрещают. Изделия без цены
        клиенту в PDF не попадут — это тот же отчёт, что у «КП (PDF)».
        """
        self.ensure_one()
        template = self.env.ref(KP_TEMPLATE, raise_if_not_found=False)
        return {
            "type": "ir.actions.act_window",
            "name": "Отправить КП",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_model": self._name,
                "default_res_ids": self.ids,
                "default_composition_mode": "comment",
                "default_template_id": template.id if template else False,
                # Как у sale: карточка нового получателя открывается с почтой.
                "force_email": True,
                # «Сохранить как шаблон / Управление шаблонами» — прячем:
                # шаблон один, правится в Настройках (список отключённого).
                "hide_mail_template_management_options": True,
                # Клиент не становится подписчиком расчёта: иначе каждое
                # сообщение в ленте расчёта уходило бы ему письмом.
                "mail_post_autofollow": False,
                KP_SEND_FLAG: True,
            },
        }

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        # Только настоящее письмо из окна «Отправить КП»: сообщение, а не
        # внутренняя заметка. Открыть окно и закрыть — сюда не попадает.
        if (self.env.context.get(KP_SEND_FLAG) and message
                and message.message_type == "comment"
                and not message.subtype_id.internal):
            self._pmk_kp_sent(message)
        return message

    def _pmk_kp_sent(self, message):
        """Письмо из окна «Отправить КП» ушло — ``message``. Точка расширения.

        В мосте пусто: письмо уже лежит в ленте расчёта. Модуль сделки
        дописывает сюда заметку в сделку и переход стадии. Было ли в письме
        само КП, решает он — по _pmk_kp_pdf(message.attachment_ids): окно
        отправляет и письмо без PDF (вложение убрали, шаблон удалён).
        """
        return True

    def _pmk_kp_pdf(self, attachments):
        """PDF КП среди вложений: файл PDF с номером расчёта в имени.

        Отчёт кладёт «КП СМ-00024.pdf»; менеджер может заменить его своим
        PDF — с тем же номером в имени он тоже КП. Чертёж без номера — нет.
        sudo: вложения окна (res_id=0) читает только их создатель, а здесь
        нужны лишь имя и тип файла.
        """
        self.ensure_one()
        number = (self.name or "").strip()
        if not number:
            return attachments.browse()
        return attachments.sudo().filtered(
            lambda att: att.mimetype == "application/pdf" and number in (att.name or ""))

    # ─── Менеджер в КП ──────────────────────────────────────────────────────
    #
    # МЕТОДОМ, А НЕ ПОЛЕМ. Модуль сделки добавляет своего кандидата (ответственный
    # сделки) переопределением одного метода; вычисляемое поле пришлось бы
    # сращивать через зависимости двух модулей. В печати метод вызывается так
    # же, как pmk_money.
    def _pmk_manager_candidates(self):
        """Кто может быть менеджером КП, по порядку. Первый подходящий — он.

        В мосте — создавший расчёт, затем текущий пользователь. Модуль
        сделки ставит впереди ответственного сделки.
        """
        self.ensure_one()
        return self.create_uid | self.env.user

    def _pmk_manager(self):
        """Первый живой внутренний пользователь из кандидатов.

        OdooBot отсеивается: он неактивен, а часть старых расчётов (СМ-15,
        21, 22) создана им — без фильтра в КП печаталось бы «OdooBot,
        odoobot@example.com».
        """
        self.ensure_one()
        return self._pmk_manager_candidates().sudo().filtered(
            lambda user: user.active and not user.share)[:1]

    def pmk_manager_line(self):
        """«Менеджер: имя, тел. …, почта» для печати; пустые части не печатаются."""
        self.ensure_one()
        user = self._pmk_manager()
        return spec_text.manager_line(user.name, user.partner_id.phone, user.partner_id.email)
