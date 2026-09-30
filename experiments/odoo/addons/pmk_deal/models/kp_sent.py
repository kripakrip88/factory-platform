# -*- coding: utf-8 -*-
"""КП отправлено — сделка это видит (разбор UX, шаг 33).

Письмо с КП уходит из окна «Отправить КП» расчёта (pmk_bridge,
models/kp_send.py). После настоящей отправки — не по нажатию кнопки, а по
«Отправить» в окне — мост зовёт _pmk_kp_sent, и здесь:

  • в ленту сделки ложится заметка «КП СМ-… отправлено: кому»;
  • стадию НЕ трогаем (решение Антона, см. ниже). Если переключатель
    KP_SENT_MOVES_STAGE включат — сделка перейдёт в «КП отправлено», но
    только вперёд: из «Заявки» и «Расчёта»; назад, из «Выиграно» и из
    проигранной — никогда.

РЕШЕНИЕ АНТОНА (документ разбора, «Уже решено»): «стадии — вариант Б, без
пятой стадии и без автоперехода». Поэтому KP_SENT_MOVES_STAGE = False:
только заметка в ленте сделки, стадию двигает менеджер. Постановка шага 33
просила автопереход — это была ошибка постановки (30.09.2026); переход
сделан и проверен тестами, но выключен. Включать — только по слову Антона.

КОГДА СТАДИЯ НЕ ДВИГАЕТСЯ. Заметка в сделке пишется всегда и говорит
словами, почему стадия осталась прежней: сигнал показывает, а не молчит.
Стадия стоит на месте в трёх случаях.

  1. В письме нет PDF КП. Вложение убрали в окне или удалили шаблон. Письмо
     ушло, а КП клиент не получил.
  2. Письмо ушло не людям клиента. Приёмку начнут с письма на свой адрес, и
     живая сделка от пробы двигаться не должна. Люди клиента — это:
       • получатель из компании клиента расчёта или сделки;
       • получатель с той же почтой, что у клиента, контактного лица или
         самой сделки;
       • получатель с того же корпоративного домена, что у них: новый адрес
         snab@arestakstroy.ru клиента «Арестак-Строй» — его человек.
         Публичные почты (mail.ru, bk.ru, gmail.com, yandex.ru…) по домену
         не считаются: там у всех один домен.
     Завод — не клиент, даже если он записан в сделку. На живой базе есть
     сделки из писем своего ящика (№1, 3, 5: почта pmkpark@mail.ru, у №1
     контакт — сама организация «ИП Чулков»), и проба на свой адрес такую
     сделку двигать не должна. Поэтому клиентом не считается:
       • организация и её люди;
       • любой внутренний пользователь;
       • почта организации, ящиков «Почты» и исходящих серверов;
       • домены этих адресов и домен псевдонимов (pmkpark.ru).
  3. У отправителя нет права менять сделку. Расчёт доступен всем
     сотрудникам, а сделка — по правилам CRM («только свои»). Право на
     расчёт не даёт права двигать чужую сделку. Такой сделки мы не
     касаемся вовсе: заметка ложится в ленту расчёта, а сделку двигает её
     ответственный.

Письмо уходит после записи транзакции (штатно для Odoo): если сервер его
отвергнет, сделка уже будет в «КП отправлено», а у письма в ленте расчёта —
красный конверт с причиной. Как и у заказа Odoo (mark_so_as_sent).
"""

from markupsafe import Markup

from odoo import models
from odoo.tools import email_normalize
from odoo.tools.misc import clean_context

# Переход стадии после отправки КП. Выключен по решению Антона «без
# автоперехода» — см. шапку файла.
KP_SENT_MOVES_STAGE = False
KP_SENT_STAGE = "crm.stage_lead3"   # «КП отправлено»

# Публичные почтовые службы: адрес на таком домене ничего не говорит о
# компании, поэтому по домену человека клиента не узнаём (только по карточке
# или по точному адресу). Список — российские службы и крупные мировые.
PUBLIC_MAIL_DOMAINS = frozenset({
    # Mail.ru
    "mail.ru", "bk.ru", "inbox.ru", "list.ru", "internet.ru", "xmail.ru", "mail.ua",
    # Яндекс
    "yandex.ru", "ya.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.ua", "narod.ru",
    # Рамблер
    "rambler.ru", "lenta.ru", "autorambler.ru", "myrambler.ru", "ro.ru", "rambler.ua",
    # прочие российские
    "qip.ru", "pochta.ru", "vk.com", "e1.ru", "ngs.ru",
    # мировые
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "live.ru",
    "msn.com", "icloud.com", "me.com", "mac.com", "yahoo.com", "aol.com",
    "proton.me", "protonmail.com", "pm.me",
})


def mail_domain(email):
    """Домен адреса в нижнем регистре: «Snab@ArestakStroy.ru» → «arestakstroy.ru»."""
    email = email_normalize(email or "") or ""
    return email.rpartition("@")[2] if "@" in email else ""


class MetalSpecKpSent(models.Model):
    _inherit = "pmk.metal.spec"

    def _pmk_manager_candidates(self):
        """Менеджер КП — прежде всего ответственный сделки (печать КП).

        sudo: КП печатает и тот, у кого нет прав на сделки (технолог), — без
        него печать упала бы на чтении ответственного чужой сделки.
        """
        return self.opportunity_id.sudo().user_id | super()._pmk_manager_candidates()

    def _pmk_kp_sent(self, message):
        res = super()._pmk_kp_sent(message)
        # Контекст окна письма тянет default_* (модель, шаблон, режим) — в
        # запись сделки и её историю им хода нет.
        for spec in self.with_context(clean_context(self.env.context)):
            deal = spec.opportunity_id
            if not deal:
                continue
            message_sudo = message.sudo()
            recipients = message_sudo.partner_ids
            to_text = ", ".join(
                partner.email_formatted or partner.name or "" for partner in recipients) or "—"
            # Права — того, кто отправил: sudo ниже их уже не проверяет.
            # Сделка ему недоступна — её не трогаем, объясняем в расчёте.
            if not deal.has_access("write"):
                spec._message_log(body=Markup(
                    "КП отправлено: %s. Сделку этого расчёта вам менять нельзя по "
                    "правам — заметку в неё не писали, стадию не меняли. Скажите "
                    "ответственному сделки.") % to_text)
                continue
            # sudo: после проверки прав — ради записи заметки и стадии без
            # оглядки на права к связанным записям. Автор заметки и истории —
            # всё равно тот, кто отправил (sudo не меняет пользователя).
            deal = deal.sudo()
            has_pdf = bool(spec._pmk_kp_pdf(message_sudo.attachment_ids))
            to_client = spec._pmk_kp_client_recipients(deal, recipients)
            if has_pdf:
                body = Markup("КП %s отправлено: %s. Письмо и PDF — в ленте расчёта.") % (
                    spec._get_html_link(), to_text)
            else:
                body = Markup("Письмо по КП %s ушло без PDF КП: %s. Письмо — в ленте расчёта.") % (
                    spec._get_html_link(), to_text)
            reason = False
            if KP_SENT_MOVES_STAGE:
                if not has_pdf:
                    reason = "КП клиент не получил — стадию не меняли."
                elif not to_client:
                    reason = "Адрес не клиента (нет в карточках, чужой домен) — стадию не меняли."
            if reason:
                body += Markup(" ") + reason
            deal._message_log(body=body)
            if KP_SENT_MOVES_STAGE and has_pdf and to_client:
                spec._pmk_kp_move_stage(deal)
        return res

    def _pmk_own_mail(self):
        """Кто «свой»: партнёры организаций, адреса и домены завода.

        Адреса: почта организаций, ящики «Почты» (mail.client.account, если
        модуль стоит), логины и from_filter исходящих серверов. Домены — их
        домены и домен псевдонимов (pmkpark.ru). sudo: это настройки, у
        менеджера прав на них нет, а читаем мы только адреса.
        """
        env = self.env
        companies = env["res.company"].sudo().search([])
        partners = companies.partner_id.commercial_partner_id
        raw = list(companies.mapped("email")) + list(companies.partner_id.mapped("email"))
        if "mail.client.account" in env:
            raw += env["mail.client.account"].sudo().with_context(
                active_test=False).search([]).mapped("email")
        domains = set()
        for server in env["ir.mail_server"].sudo().with_context(active_test=False).search([]):
            raw.append(server.smtp_user)
            for part in (server.from_filter or "").split(","):
                part = part.strip().lower()
                if "@" in part:
                    raw.append(part)
                elif part:
                    domains.add(part)
        emails = {email_normalize(email) for email in raw if email} - {False, None, ""}
        domains |= {mail_domain(email) for email in emails}
        if "mail.alias.domain" in env:
            domains |= {
                (name or "").strip().lower()
                for name in env["mail.alias.domain"].sudo().search([]).mapped("name")}
        domains.discard("")
        return partners, emails, domains

    def _pmk_kp_client_recipients(self, deal, recipients):
        """Кто из получателей письма — люди клиента (см. шапку файла)."""
        self.ensure_one()
        own_partners, own_emails, own_domains = self._pmk_own_mail()
        clients = (self.partner_id | self.contact_id | deal.partner_id).commercial_partner_id
        clients -= own_partners
        client_emails = {
            email for email in (
                self.partner_id.email_normalized, self.contact_id.email_normalized,
                deal.partner_id.email_normalized, deal.email_normalized,
            ) if email
        } - own_emails
        client_domains = ({mail_domain(email) for email in client_emails}
                          - PUBLIC_MAIL_DOMAINS - own_domains - {""})

        def is_client(partner):
            email = partner.email_normalized
            if not email or email in own_emails:
                return False
            if partner.commercial_partner_id in own_partners:
                return False
            if partner.user_ids.filtered(lambda user: not user.share):
                return False                         # сотрудник завода
            return (partner.commercial_partner_id in clients
                    or email in client_emails
                    or mail_domain(email) in client_domains)

        return recipients.sudo().filtered(is_client)

    def _pmk_kp_move_stage(self, deal):
        """«КП отправлено» — только вперёд. Вернёт True, если стадию сменили.

        Не трогаем: проигранную (в архиве или won_status «lost»), выигранную,
        стоящую в «КП отправлено» или дальше. Историю смены запишет ядро
        (tracking), счётчик «зависания» стадии сбросится сам
        (date_last_stage_update).
        """
        target = self.env.ref(KP_SENT_STAGE, raise_if_not_found=False)
        stage = deal.stage_id
        if not target or not deal.active or deal.won_status != "pending" or stage.is_won:
            return False
        if stage and (stage.sequence, stage.id) >= (target.sequence, target.id):
            return False
        deal.stage_id = target
        return True
