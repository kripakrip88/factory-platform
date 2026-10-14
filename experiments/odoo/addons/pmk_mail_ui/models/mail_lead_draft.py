# -*- coding: utf-8 -*-
"""Окно «Новый лид из письма» (14.10.2026, по образцу «Новый контрагент из
письма»): что ляжет в лид и откуда взято — до создания, с правкой.

Собирает то же, что «Лид из письма» делал сразу (_pmk_create_lead): название
из темы без «RE:/FW:», клиент по адресу, ИНН или домену, имя контакта и
телефон из подписи, почта. Создаёт по-прежнему action_pmk_create_lead —
поправленное в окне приходит в него overrides.
"""

from odoo import _, api, fields, models

from ..tools import lead_text, signature

HOW = {"inn": "по ИНН из письма", "domain": "по домену адреса"}


class MailClientMessage(models.Model):
    _inherit = "mail.client.message"

    @api.model
    def pmk_lead_draft(self, message_id):
        """-> {"existing": {"id", "name"} | False, "lead", "lead_sources",
        "client", "candidates", "contact", "contact_sources", "attachments",
        "sender", "email", "subject"}. Ничего не создаёт."""
        message = self._checked(message_id, "read")
        if not self.env["crm.lead"].has_access("create"):
            return {"denied": True}
        existing = message._pmk_find_lead()
        if existing:
            return {"existing": {"id": existing.id, "name": existing.display_name}}

        own = self._pmk_own_addresses()
        sender, address = lead_text.split_sender(message.email_from)
        lines = signature.own_lines(message.body_html or "", message.subject)

        client, candidates, how = message.partner_id, self.env["res.partner"], "по адресу письма"
        if not client:
            match = message._pmk_client_from_letter(address, lines, own)
            if match and match["partners"]:
                if len(match["partners"]) == 1:
                    client = match["partners"]
                else:
                    candidates = match["partners"][:5]
                how = HOW.get(match["how"], "") if match else ""

        received = ""
        if message.date:
            received = fields.Datetime.context_timestamp(self, message.date).strftime("%d.%m.%Y %H:%M")
        lead = {
            "name": lead_text.clean_subject(message.subject) or _("Без темы"),
            "received": received,
            "manager": self.env.user.name,
        }
        contact, csources = {}, {}
        if not client or client.is_company:
            person = lead_text.contact_name(sender, address, own)
            if person:
                contact["contact_name"], csources["contact_name"] = person, "имя отправителя"
        phone = message._pmk_letter_phone(address, lines, own, client)
        if phone:
            contact["phone"], csources["phone"] = phone, "подпись"
        if address:
            contact["email_from"], csources["email_from"] = address, "письмо"

        parts = message.client_attachment_ids.filtered(lambda part: not part.pmk_inline)
        return {
            "existing": False,
            "sender": sender or "", "email": address or "", "subject": message.subject or "",
            "lead": lead,
            "lead_sources": {"name": "тема", "received": "письмо", "manager": "кто создаёт"},
            "client": ({"id": client.id, "name": client.display_name, "how": how}
                       if client else False),
            "candidates": [{"id": item.id, "name": item.display_name} for item in candidates],
            "candidates_how": how if candidates else "",
            "contact": contact,
            "contact_sources": csources,
            "attachments": parts.mapped("name"),
        }
