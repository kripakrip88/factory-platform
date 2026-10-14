# -*- coding: utf-8 -*-
"""Карточка контрагента справа от письма (редизайн почты, шаг 7, 14.10.2026).

Кто пишет и что с ним сейчас: ИНН, город, менеджер, писем за год, открытые
сделки и последние счета — не выходя из почты. Кнопки: «Лид из письма»,
«Привязать к сделке», «Открыть контрагента».

Контрагент ищется так же, как при «Лид из письма», в порядке надёжности:
клиент сделки, к которой письмо уже привязано; точный адрес; ИНН из текста
письма и домен адреса (pmk_partner, если стоит). У своего письма — по
первому получателю. Адреса завода (пересылка коллеги) клиента не дают.

Только чтение, кроме «Привязать к сделке»: письмо ложится в чат сделки тем же
путём, что у «Лид из письма» (_pmk_post_letter), и строка письма получает
значок сделки (pmk_lead_id).
"""

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize
from odoo.tools.mail import email_split
from odoo.tools.misc import format_amount, format_date

from ..tools import lead_text, signature

SHOWN = 3


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    # ------------------------------------------------------------------
    # чтение
    # ------------------------------------------------------------------
    def _pmk_card_address(self, own_addresses):
        """Адрес «того, кто по ту сторону»: у своего письма — первый чужой
        получатель, иначе отправитель. Адрес завода — пусто."""
        self.ensure_one()
        if self._is_outgoing():
            raw = email_split("%s,%s" % (self.email_to or "", self.email_cc or ""))
        else:
            raw = email_split(self.email_from or "")
        for item in raw:
            address = email_normalize(item)
            if address and address not in own_addresses:
                return address
        return ""

    def _pmk_card_partner(self):
        """-> (компания или человек без компании, кандидаты, как нашли)."""
        self.ensure_one()
        Partner = self.env["res.partner"]
        if self.pmk_lead_id.partner_id:
            return self.pmk_lead_id.partner_id.commercial_partner_id, Partner, "lead"
        own = self._pmk_own_addresses()
        address = self._pmk_card_address(own)
        if self.partner_id and not self._is_outgoing() and address:
            return self.partner_id.commercial_partner_id, Partner, "email"
        if address:
            found = Partner.search([("email_normalized", "=", address)], limit=1)
            if found:
                return found.commercial_partner_id, Partner, "email"
        lines = signature.own_lines(self.body_html or "", self.subject)
        match = self._pmk_client_from_letter(address, lines, own) if address or lines else None
        if match and match["partners"]:
            partners = match["partners"]
            if len(partners) == 1:
                return partners, Partner, match["how"]
            return Partner, partners[:5], match["how"]
        return Partner, Partner, False

    @api.model
    def pmk_partner_card(self, message_id):
        message = self._checked(message_id, "read")
        partner, candidates, how = message._pmk_card_partner()
        own = self._pmk_own_addresses()
        address = message._pmk_card_address(own)
        sender, _addr = lead_text.split_sender(
            message.email_to if message._is_outgoing() else message.email_from)
        card = {
            "email": address,
            "sender": sender or "",
            "how": how,
            "partner": False,
            "candidates": [{"id": item.id, "name": item.display_name} for item in candidates],
            "letters_year": 0,
            "deals": [],
            "deals_total": 0,
            "invoices": [],
            "invoices_total": 0,
            "lead": ({"id": message.pmk_lead_id.id, "name": message.pmk_lead_id.display_name}
                     if message.pmk_lead_id else False),
            "can_lead": self.env["crm.lead"].has_access("create"),
            "can_link": self.env["crm.lead"].has_access("write"),
        }
        if not partner:
            return card

        card["partner"] = {
            "id": partner.id,
            "name": partner.display_name,
            "vat": partner.vat or "",
            "city": partner.city or "",
            "phone": partner.phone or "",
            "manager": partner.user_id.name or "",
        }
        year_ago = fields.Datetime.now() - timedelta(days=365)
        emails = {email_normalize(item) for item in
                  self.env["res.partner"].search(
                      [("id", "child_of", partner.id)]).mapped("email") if item}
        emails.discard(False)
        if emails:
            domain = ["|"] * (len(emails) - 1)
            for item in emails:
                domain.append(("email_from", "ilike", item))
            card["letters_year"] = self.search_count(
                [("date", ">=", year_ago), ("account_id", "=", message.account_id.id)] + domain)
        card.update(self._pmk_card_deals(partner, message.pmk_lead_id))
        card.update(self._pmk_card_invoices(partner))
        return card

    @api.model
    def _pmk_card_deals(self, partner, current):
        Lead = self.env["crm.lead"]
        if not Lead.has_access("read"):
            return {}
        domain = [("partner_id", "child_of", partner.id), ("type", "=", "opportunity"),
                  ("won_status", "=", "pending")]
        total = Lead.search_count(domain)
        deals = Lead.search(domain, order="write_date desc", limit=SHOWN)
        currency = self.env.company.currency_id
        return {
            "deals_total": total,
            "deals": [{
                "id": deal.id,
                "name": deal.name,
                "stage": deal.stage_id.name or "",
                "amount": format_amount(self.env, deal.expected_revenue, deal.company_currency or currency)
                          if deal.expected_revenue else "",
                "current": deal == current,
            } for deal in deals],
        }

    @api.model
    def _pmk_card_invoices(self, partner):
        if "sale.order" not in self.env:
            return {}
        Order = self.env["sale.order"]
        if not Order.has_access("read"):
            return {}
        domain = [("partner_id", "child_of", partner.id), ("state", "!=", "cancel")]
        total = Order.search_count(domain)
        orders = Order.search(domain, order="date_order desc, id desc", limit=SHOWN)
        status_field = Order._fields.get("pmk_status")

        def status(order):
            if "pmk_ms_state" in Order._fields and order.pmk_ms_state:
                return order.pmk_ms_state
            if status_field and order.pmk_status:
                return dict(status_field._description_selection(self.env)).get(order.pmk_status, "")
            return ""

        return {
            "invoices_total": total,
            "invoices": [{
                "id": order.id,
                "name": order.name,
                "status": status(order),
                "amount": format_amount(self.env, order.amount_total, order.currency_id),
                "date": format_date(self.env, order.date_order.date()) if order.date_order else "",
            } for order in orders],
        }

    # ------------------------------------------------------------------
    # «Привязать к сделке»
    # ------------------------------------------------------------------
    @api.model
    def pmk_link_lead(self, message_id, lead_id):
        message = self._checked(message_id, "read")
        lead = self.env["crm.lead"].browse(lead_id).exists()
        if not lead:
            raise UserError(_("Сделка не найдена — возможно, её удалили."))
        lead.check_access("write")
        posted = bool(message.message_id) and self.env["mail.message"].sudo().search_count([
            ("message_id", "=", message.message_id),
            ("model", "=", "crm.lead"),
            ("res_id", "=", lead.id),
        ])
        if not posted:
            attachments, failed = message._pmk_letter_attachments()
            message._pmk_post_letter(lead, attachments, "mail.mt_comment")
            message._pmk_note_failed(lead, failed)
        # sudo точечно на одно наше поле — как у «Лид из письма».
        if message.pmk_lead_id != lead:
            message.sudo().pmk_lead_id = lead.id
        return {"id": lead.id, "name": lead.display_name, "posted": not posted}
