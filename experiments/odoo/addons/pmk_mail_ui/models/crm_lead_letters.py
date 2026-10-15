# -*- coding: utf-8 -*-
"""Вкладка «Письма» в сделке (15.10.2026).

Антон 15.10: «когда создаём сделку из письма, текст письма и файлы… либо окно
ниже с письмом и файлами, приходится переключаться — это очень неудобно, либо
иметь возможность открыть письмо в отдельном окне из сделки». Прототип принят
(«отлично»): слева письма сделки, справа текст и вложения выбранного, кнопки
«Ответить», «Открыть в почте», «В отдельном окне».

И дополнение: «отображение вообще всех писем отправителя, чтоб допривязать к
сделке доп. письма, если вдруг в письме затёрли тему» — блок «Ещё письма
клиента — не привязаны»: по адресам контакта сделки и всех контактов его
компании, по домену компании (не mail.ru/gmail), в обе стороны (от клиента и
наши ему), за 3 месяца, дальше — «за всё время». Письмо другой сделки — серым
с её номером, перепривязка с подтверждением. Привязка — штатная «Привязать к
сделке» (pmk_link_lead): письмо и файлы встают в ленту сделки, файлы — во
вкладку «Файлы».

Письма сделки — привязанные к ней (pmk_lead_id) и их переписка в том же ящике
(как значок лида у строки почты, mail_client_step41._pmk_thread_leads), кроме
писем переписки, привязанных к другой сделке.

Видно только то, что человеку видно в почте: ящики _accessible_accounts и
правила записи письма (поиск — от его имени).
"""
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..tools import deal_letters as rules

CANDIDATE_DAYS = 90
CANDIDATE_LIMIT = 40
CANDIDATE_LIMIT_ALL = 200
# Сырых строк с запасом: копии одного письма в двух папках и ложные
# совпадения LIKE («_» в адресе) отсеются уже здесь, в питоне.
RAW_FACTOR = 3


class MailClientMessageDeal(models.Model):
    _inherit = "mail.client.message"

    def _pmk_deal_row(self, lead_badges=None, reason=None, direct=False):
        """Строка списка писем во вкладке сделки."""
        self.ensure_one()
        badge = (lead_badges or {}).get(self.id)
        return {
            "id": self.id,
            "subject": self.subject or _("(без темы)"),
            "date": self.date and fields.Datetime.to_string(self.date),
            "email_from": self.email_from or "",
            "email_to": self.email_to or "",
            "is_outgoing": self._is_outgoing(),
            "preview": self.preview or "",
            "has_attachment": bool(self.has_attachment),
            "direct": direct,
            "reason": reason,
            "lead": badge or False,
        }

    @api.model
    def pmk_unlink_lead(self, message_id, lead_id):
        """«Отвязать» во вкладке «Письма». Письмо, уже переложенное в ленту
        сделки (с файлами), там и остаётся: это история сделки, а не ссылка."""
        message = self._checked(message_id, "read")
        lead = self.env["crm.lead"].browse(lead_id).exists()
        if not lead:
            raise UserError(_("Сделка не найдена — возможно, её удалили."))
        lead.check_access("write")
        if message.pmk_lead_id != lead:
            raise UserError(_(
                "Это письмо в сделке по переписке: привязано другое письмо той же "
                "переписки. Отвяжите его."))
        # sudo точечно на одно наше поле — как у «Привязать к сделке».
        message.sudo().pmk_lead_id = False
        return True

    @api.model
    def pmk_letter_mail_action(self, message_id, reply=False):
        """«Открыть в почте» / «Ответить»: почта на этом письме (шаг 53), с
        reply — сразу с ответом под письмом. False — письма нет в почте
        человека (ящик не его, папка не подписана)."""
        message = self._checked(message_id, "read")
        if not message._pmk_tree_folder_id():
            return False
        try:
            action = self.env["ir.actions.actions"]._for_xml_id("pmk_mail_ui.action_mail_sale")
        except (ValueError, AccessError):
            return False
        action = dict(action)
        action["params"] = dict(action.get("params") or {}, pmk_message_id=message.id,
                                pmk_reply=bool(reply))
        return action


class CrmLeadLetters(models.Model):
    _inherit = "crm.lead"

    # ------------------------------------------------------------------
    # чьи письма
    # ------------------------------------------------------------------
    @api.model
    def _pmk_public_domains(self):
        public = set(rules.PUBLIC_MAIL_DOMAINS)
        try:
            from odoo.addons.pmk_partner.tools import partner_keys
            public |= set(partner_keys.PUBLIC_MAIL_DOMAINS)
        except ImportError:
            pass
        extra = self.env["ir.config_parameter"].sudo().get_param("pmk_partner.public_mail_domains") or ""
        public |= {item.strip().lower() for item in extra.split(",") if item.strip()}
        return public

    @api.model
    def _pmk_own_mail_addresses(self):
        own = self.env["mail.client.account"].sudo().search([]).mapped("email")
        own += self.env["res.company"].sudo().search([]).mapped("email")
        return [item for item in own if item]

    def _pmk_client_mail_keys(self):
        """(адреса, домены) клиента сделки: адрес сделки, контакт, его
        компания и все её контакты."""
        self.ensure_one()
        partner = self.partner_id
        company = partner.commercial_partner_id
        people = (partner | company | company.child_ids).sudo()
        emails = [self.email_from or ""] + [item for item in people.mapped("email") if item]
        return rules.client_keys(emails, self._pmk_own_mail_addresses(), self._pmk_public_domains())

    def _pmk_linked_letters(self):
        """(письма сделки новыми сверху без копий, привязанные напрямую)."""
        self.ensure_one()
        Msg = self.env["mail.client.message"]
        accounts = self.env["mail.client.account"]._accessible_accounts()
        direct = Msg.search([("pmk_lead_id", "=", self.id), ("account_id", "in", accounts.ids)])
        keys = sorted({key for key in direct.mapped("thread_key") if key})
        thread = Msg
        if keys:
            thread = Msg.search([
                ("thread_key", "in", keys),
                ("account_id", "in", direct.account_id.ids),
                "|", ("pmk_lead_id", "=", False), ("pmk_lead_id", "=", self.id),
            ])
        letters = (direct | thread).sorted(
            key=lambda m: (m.date or datetime.min, m.id), reverse=True)._without_duplicates()
        return letters, direct

    def _pmk_candidate_letters(self, mails, domains, exclude, show_all):
        """Письма клиента, не привязанные к этой сделке: [(письмо, причина)],
        и есть ли ещё старше 3 месяцев."""
        self.ensure_one()
        Msg = self.env["mail.client.message"]
        accounts = self.env["mail.client.account"]._accessible_accounts()
        # Домен — без «@»: у адреса бывает поддомен (buh@zavod.example.org
        # при домене example.org). Лишнее (example.org.ru, «_» в LIKE) отсеет
        # match_reason по разобранным адресам.
        needles = list(mails) + list(domains)
        if not needles or not accounts:
            return [], False
        terms = [(field_name, "ilike", needle) for needle in needles
                 for field_name in ("email_from", "email_to", "email_cc")]
        address_domain = ["|"] * (len(terms) - 1) + terms
        base = [("account_id", "in", accounts.ids), ("id", "not in", exclude.ids),
                ("is_spam", "=", False)] + address_domain
        cutoff = fields.Datetime.now() - timedelta(days=CANDIDATE_DAYS)
        limit = CANDIDATE_LIMIT_ALL if show_all else CANDIDATE_LIMIT
        domain = base if show_all else base + [("date", ">=", cutoff)]
        raw = Msg.search(domain, order="date desc, id desc", limit=limit * RAW_FACTOR)
        # Копия привязанного письма в другой папке («Входящие» + «Отправленные»)
        # — то же письмо: в «не привязаны» её не показываем.
        linked_ids = {(m.account_id.id, m.message_id) for m in exclude if m.message_id}
        found = []
        for message in raw._without_duplicates():
            if message.message_id and (message.account_id.id, message.message_id) in linked_ids:
                continue
            reason = rules.match_reason(
                rules.addresses(message.email_from, message.email_to, message.email_cc), mails, domains)
            if reason:
                found.append((message, reason))
            if len(found) >= limit:
                break
        older = False
        if not show_all:
            older = bool(Msg.search(base + [("date", "<", cutoff)], limit=1))
        return found, older

    # ------------------------------------------------------------------
    # вкладка
    # ------------------------------------------------------------------
    @api.model
    def pmk_deal_letters(self, lead_id, show_all=False):
        lead = self.browse(lead_id).exists()
        if not lead:
            return {"letters": [], "candidates": []}
        lead.check_access("read")
        Msg = self.env["mail.client.message"]
        if not Msg.has_access("read"):
            return {"no_access": True, "letters": [], "candidates": []}
        letters, direct = lead._pmk_linked_letters()
        mails, domains = lead._pmk_client_mail_keys()
        found, older = lead._pmk_candidate_letters(mails, domains, letters, show_all)
        candidates = Msg.browse([message.id for message, _reason in found])
        badges = candidates._pmk_thread_leads()
        # Номер «СД-…» (pmk_deal; без него — название): по нему Антон узнаёт
        # сделку в сером «в сделке …».
        Lead = self.with_context(active_test=False)
        for badge in badges.values():
            other = Lead.browse(badge["id"])
            badge["number"] = (other.pmk_number if "pmk_number" in other._fields else False) or ""
            badge["same"] = badge["id"] == lead.id
        return {
            "letters": [m._pmk_deal_row(direct=m in direct) for m in letters],
            "candidates": [m._pmk_deal_row(badges, reason) for m, reason in found],
            "older": older,
            "show_all": bool(show_all),
            "mails": mails,
            "domains": domains,
            "days": CANDIDATE_DAYS,
            "can_write": lead.has_access("write"),
        }
