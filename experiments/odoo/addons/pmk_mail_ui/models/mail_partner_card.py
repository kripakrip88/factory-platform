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

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize
from odoo.tools.mail import email_split
from odoo.tools.misc import format_amount, format_date

from ..tools import lead_text, requisites, signature

_logger = logging.getLogger(__name__)

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
        # У клиентов почта в карточке почти не заполнена — считаем и по адресу
        # самого письма (Сфера-Строй: найдена по ИНН, почты в карточке нет).
        if address:
            emails.add(address)
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

    # ------------------------------------------------------------------
    # «Создать контрагента» из письма (14.10.2026)
    # ------------------------------------------------------------------
    # Сколько вложений читать и каких: только с текстом, не больше пяти — по
    # каждому отдельный вход в ящик (только чтение, EXAMINE).
    READ_PARTS = 5

    def _pmk_requisites_from_parts(self, own_inns):
        """Реквизиты и названия организаций из вложений письма:
        (найденное, имя файла с реквизитами | False, [названия], имя файла с
        названиями | False)."""
        self.ensure_one()
        merged = requisites.requisites("")
        source = names_source = False
        names = []
        parts = self.client_attachment_ids.filtered(
            lambda part: not part.pmk_inline
            and requisites.file_kind(part.name, part.content_type)
            and (part.file_size or 0) <= requisites.MAX_BYTES)
        for part in parts[:self.READ_PARTS]:
            try:
                stored = part.sudo()._fetch()
            except UserError as exc:
                _logger.info("Реквизиты: вложение %s не скачано: %s", part.name, exc)
                continue
            text = requisites.attachment_text(part.name, part.content_type, stored.sudo().raw)
            found = requisites.requisites(text, own_inns)
            useful = False
            for key, value in found.items():
                if value and not merged[key]:
                    merged[key] = value
                    useful = True
            if useful and not source:
                source = part.name
            for name in requisites.legal_names_in(text, self._pmk_own_names()):
                if name not in names:
                    names.append(name)
                    names_source = names_source or part.name
        return merged, source, names, names_source

    @api.model
    def _pmk_own_names(self):
        """Свои организации — их названия во вложениях (договор, акт) не
        клиент: «ИП «…»», «ООО «…»» компаний Odoo и «Наших организаций»."""
        env = self.env
        partners = env["res.company"].sudo().search([]).partner_id
        if "pmk.org" in env:
            partners |= env["pmk.org"].sudo().with_context(active_test=False).search([]).partner_id
        own = set()
        for partner in partners:
            for value in (partner.name, getattr(partner, "pmk_legal_name", "")):
                if value:
                    own.add(value)
                    own.update(requisites.legal_names_in(value))
        return own

    # Поля организации, которые окно «Новый контрагент» может прислать назад.
    COMPANY_KEYS = ("name", "vat", "kpp", "ogrn", "okpo", "pmk_legal_name",
                    "pmk_legal_address", "pmk_dadata_status", "fias_id", "zip", "city", "street")
    CONTACT_KEYS = ("name", "function", "phone", "email")

    @api.model
    def _pmk_dadata_company(self, data):
        """Ответ справочника → поля организации для окна (+ ИНН)."""
        Partner = self.env["res.partner"]
        values, status = Partner._pmk_dadata_values(data)
        company = {key: value for key, value in values.items() if value and key in self.COMPANY_KEYS}
        if data.get("inn"):
            company["vat"] = data["inn"]
        company["status"] = Partner._pmk_status_label(status) if status else ""
        company["active"] = not status or status == "ACTIVE"
        address = data.get("address") or {}
        company["place"] = (address.get("value") or "")[:90]
        return company

    @api.model
    def pmk_partner_suggest(self, query):
        """Похожие организации из справочника по названию — для окна."""
        Partner = self.env["res.partner"]
        if not hasattr(Partner, "_pmk_dadata_suggest"):
            return []
        return self._pmk_mark_existing(
            [self._pmk_dadata_company(data) for data in Partner._pmk_dadata_suggest(query)])

    @api.model
    def _pmk_mark_existing(self, items):
        """Организации справочника, которые уже есть в базе (по ИНН): новый
        контрагент не нужен — отправителя добавляем к ней контактом."""
        Partner = self.env["res.partner"].with_context(active_test=False)
        for item in items:
            inn = item.get("vat")
            existing = Partner.search([("vat", "in", [inn, "RU" + inn])], limit=1) if inn else Partner
            if existing:
                company = existing.commercial_partner_id
                item["existing_id"] = company.id
                item["existing_name"] = company.display_name
        # Уже знакомая организация — скорее всего, она и есть: первой.
        return sorted(items, key=lambda item: not item.get("existing_id"))

    @api.model
    def pmk_partner_from_letter(self, message_id):
        """Что нашлось в письме для «Новый контрагент из письма» — с
        источниками. Ничего не сохраняет. -> {"existing", "company",
        "company_sources", "query", "candidates", "contact", "contact_sources",
        "bank", "notes", "warnings", "sender", "email", "subject"}."""
        message = self._checked(message_id, "read")
        Partner = self.env["res.partner"]
        Partner.check_access("create")
        own = self._pmk_own_addresses()
        address = message._pmk_card_address(own)
        sender, _addr = lead_text.split_sender(
            message.email_to if message._is_outgoing() else message.email_from)
        lines = signature.own_lines(message.body_html or "", message.subject)
        own_inns = (Partner._pmk_own_inns() if hasattr(Partner, "_pmk_own_inns") else set())
        domain = address.split("@", 1)[-1] if address else ""

        letter = requisites.requisites(signature.letter_text(lines), own_inns)
        attached, source, attached_names, names_source = message._pmk_requisites_from_parts(own_inns)
        found = {key: value or attached[key] for key, value in letter.items()}
        result = {
            "sender": sender or "", "email": address, "subject": message.subject or "",
            "existing": False, "company": {}, "company_sources": {}, "query": "",
            "candidates": [], "contact": {}, "contact_sources": {}, "bank": {},
            "warnings": [],
        }
        company, sources = result["company"], result["company_sources"]

        inn = (found["inns"] or [""])[0]
        if inn:
            where = "письмо" if letter["inns"] else "вложение «%s»" % source
            existing = Partner.with_context(active_test=False).search(
                [("vat", "in", [inn, "RU" + inn])], limit=1)
            company["vat"] = inn
            sources["vat"] = where
            finder = getattr(Partner, "_pmk_dadata_find", None)
            if existing:
                existing = existing.commercial_partner_id
                company.update({
                    "name": existing.display_name, "existing_id": existing.id,
                    "existing_name": existing.display_name, "kpp": existing.kpp or "",
                    "pmk_legal_address": getattr(existing, "pmk_legal_address", "") or "",
                })
                sources["name"] = "уже в базе"
            elif finder:
                try:
                    company.update(self._pmk_dadata_company(finder(inn)))
                    for key in company:
                        sources.setdefault(key, "справочник")
                except UserError as exc:
                    result["warnings"].append(_("Справочник по ИНН не ответил: %s", exc.args[0]))
            if len(found["inns"]) > 1:
                result["warnings"].append(_("В письме несколько ИНН (%s) — взят первый.",
                                            ", ".join(found["inns"])))
        for key in ("kpp", "ogrn"):
            if found[key] and not company.get(key):
                company[key] = found[key]
                sources[key] = "письмо" if letter[key] else "вложение"

        # Без ИНН — название для поиска в справочнике: подпись, вложение,
        # имя отправителя с правовой формой; домен — последним.
        if not company.get("name"):
            named = requisites.company_from_lines(lines, domain)
            name_source = "подпись"
            # Правовое название в теме или тексте письма: «ООО "Альфамобиль" О
            # предстоящем платеже…» у писем-роботов без подписи.
            in_letter = requisites.legal_names_in(
                "%s\n%s" % (message.subject or "", signature.letter_text(lines)), self._pmk_own_names())
            if not named and in_letter:
                named, name_source = in_letter[0], "письмо"
            query_sources = {name: "письмо" for name in in_letter}
            query_sources.update({name: "вложение" for name in attached_names
                                  if name not in query_sources})
            attached_names = [name for name in in_letter if name != named] + [
                name for name in attached_names if name not in in_letter]
            if not named and attached_names:
                named, name_source = attached_names[0], "вложение"
            if not named:
                named, name_source = requisites.company_from_sender(sender), "имя отправителя"
            if not named and domain:
                named, name_source = domain, "адрес"
            if named:
                company["name"] = named
                sources["name"] = name_source
            if not inn:
                # Домен справочник по названию не ищет — только как подсказка.
                queries = [query for query in
                           ([named] if name_source != "адрес" else []) + attached_names if query][:2]
                result["query"] = queries[0] if queries else ""
                seen = set()
                per_query = 5 if len(queries) == 1 else 3
                for query in queries:
                    try:
                        for item in self.pmk_partner_suggest(query)[:per_query]:
                            if item.get("vat") and item["vat"] not in seen and item["vat"] not in own_inns:
                                seen.add(item["vat"])
                                item["source"] = (name_source if query == named
                                                  else query_sources.get(query, ""))
                                result["candidates"].append(item)
                    except UserError as exc:
                        result["warnings"].append(_("Справочник не ответил: %s", exc.args[0]))
                        break
                result["candidates"] = sorted(
                    result["candidates"], key=lambda item: not item.get("existing_id"))[:5]

        # Контакт — человек из письма.
        contact, csources = result["contact"], result["contact_sources"]
        if requisites.looks_like_person(sender):
            contact["name"], csources["name"] = sender, "имя отправителя"
        else:
            person = requisites.person_from_lines(lines)
            if person:
                contact["name"], csources["name"] = person, "подпись"
        position = requisites.position_from_lines(lines)
        if position:
            contact["function"], csources["function"] = position, "подпись"
        own_digits = {signature.phone_digits(phone) for phone in self._pmk_own_phones()}
        phone = requisites.contact_phone(lines, own_digits) if address else ""
        if phone:
            contact["phone"], csources["phone"] = phone, "подпись"
        if address:
            contact["email"], csources["email"] = address, "письмо"

        if found["account"]:
            bank = self.env["res.bank"].search([("bic", "=", found["bik"])], limit=1) \
                if found["bik"] else self.env["res.bank"]
            result["bank"] = {"acc_number": found["account"], "bik": found["bik"],
                              "bank_id": bank.id or False, "bank_name": bank.name or "",
                              "source": "письмо" if letter["account"] else "вложение «%s»" % source}
        return result

    @api.model
    def _pmk_partner_values(self, company, contact, bank):
        """Значения новой карточки из окна: только известные поля."""
        Partner = self.env["res.partner"]
        values = {key: value for key, value in (company or {}).items()
                  if key in self.COMPANY_KEYS and value and key in Partner._fields}
        if not values.get("name"):
            raise UserError(_("Укажите название организации."))
        values.update({"is_company": True, "company_type": "company"})
        ru = self.env.ref("base.ru", raise_if_not_found=False)
        if ru:
            values["country_id"] = ru.id
        person = {key: value for key, value in (contact or {}).items()
                  if key in self.CONTACT_KEYS and value}
        if person.get("name") or person.get("phone"):
            person.setdefault("name", person.get("email") or _("Контакт"))
            person["type"] = "contact"
            values["child_ids"] = [fields.Command.create(person)]
        elif person.get("email"):
            values["email"] = person["email"]
        if (bank or {}).get("acc_number"):
            line = {"acc_number": bank["acc_number"]}
            if bank.get("bank_id"):
                line["bank_id"] = bank["bank_id"]
            values["bank_ids"] = [fields.Command.create(line)]
        return values

    @api.model
    def pmk_partner_create_from_letter(self, message_id, company, contact=None, bank=None):
        """«Создать контрагента» в окне: карточка организации, контакт и
        счёт. ИНН уже есть в базе — не дублируем, отдаём существующую."""
        self._checked(message_id, "read")
        Partner = self.env["res.partner"]
        Partner.check_access("create")
        inn = (company or {}).get("vat") or ""
        if inn:
            existing = Partner.with_context(active_test=False).search(
                [("vat", "in", [inn, "RU" + inn])], limit=1)
            if existing:
                partner = existing.commercial_partner_id
                added = self._pmk_add_contact(partner, contact)
                return {"id": partner.id, "name": partner.display_name, "created": False,
                        "contact_added": added.name if added else False}
        partner = Partner.create(self._pmk_partner_values(company, contact, bank))
        return {"id": partner.id, "name": partner.display_name, "created": True,
                "contact_added": False}

    @api.model
    def _pmk_add_contact(self, company, contact):
        """Отправитель — контактом к уже заведённому контрагенту: в следующий
        раз карточка справа узнает его по адресу. Такой адрес у компании или
        её контактов уже есть — ничего не добавляем."""
        person = {key: value for key, value in (contact or {}).items()
                  if key in self.CONTACT_KEYS and value}
        email = email_normalize(person.get("email") or "")
        if not (person.get("name") or email):
            return self.env["res.partner"]
        if email and self.env["res.partner"].with_context(active_test=False).search_count([
                ("id", "child_of", company.id), ("email_normalized", "=", email)]):
            return self.env["res.partner"]
        person.setdefault("name", person.get("email"))
        person.update({"parent_id": company.id, "type": "contact"})
        return self.env["res.partner"].create(person)
