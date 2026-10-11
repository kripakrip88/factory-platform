# -*- coding: utf-8 -*-
"""Клиент из письма: не плодить дубли (шаг З-14, 10.10.2026).

Один общий поиск клиента на res.partner — его зовут лид из письма
(pmk_mail_ui, _pmk_create_lead), правило ядра «найти клиента лида»
(models/crm_lead.py, _find_matching_partner — им пользуется мастер «В
сделку») и экран «Возможные дубли» (models/partner_duplicate.py).

ПОИСК КЛИЕНТА (_pmk_find_company). Почтовый модуль и ядро ищут контакт по
полю «Эл. почта» целиком. У завода почта у клиентов почти не заполнена
(боевая база 10.10: эл. почта у 6 контрагентов из 197, сайт у 38, почта для
прайсов у 72), поэтому точное совпадение почти никогда не срабатывает.
Здесь — по порядку:
  1. ИНН из текста письма (только с верными контрольными цифрами, без
     своих ИНН) — по полю vat. В российской локализации поле inn —
     зеркало vat (l10n_ru_doc, related, не хранится), искать по нему
     отдельно нечего;
  2. домен адреса — у почты, сайта и почты для прайсов карточки и её
     контактов (truboproduct.ru у 6574@…, hab.truboproduct.ru и
     hbr@truboproduct.ru). Общие почтовые домены, свои домены и домены,
     переданные вызывающим, не связывают.
Находка сводится к компании (commercial_partner_id), и клиентом бывает
только организация (is_company): человек верхнего уровня (на бою —
карточка 92 «Заявка Листы гладкие окрашенные» с адресом на bvbmail.ru) по
домену или ИНН не ставится — иначе ядро записало бы адрес и телефон
другого отправителя в его карточку, а лид взял бы его адрес вместо адреса
письма. Человека находит только точный адрес (почтовый модуль и ядро).
Своя организация, её контакты и пользователи Odoo клиентом не бывают. Среди находок есть
активные — берём только их; иначе архивные с пометкой «в архиве»: реестр
поставщиков лежит в архиве, а филиал из него бывает и покупателем.

Одна находка — клиент найден. Несколько — НЕ УГАДЫВАЕМ: вызывающий
показывает список и оставляет выбор человеку (наблюдать, а не решать).
"""

from odoo import api, models

from ..tools import partner_keys

PUBLIC_DOMAINS_PARAM = "pmk_partner.public_mail_domains"


class ResPartnerMatch(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # свои
    # ------------------------------------------------------------------
    @api.model
    def _pmk_own_partner_ids(self):
        """Карточки, которые клиентом не бывают: свои организации (компании
        Odoo и «Наши организации») с их контактами и пользователи Odoo.
        sudo: настройки компаний и пользователей менеджеру читать не нужно,
        берём только номера карточек."""
        env = self.env
        Partner = self.sudo().with_context(active_test=False)
        roots = env["res.company"].sudo().search([]).partner_id
        if "pmk.org" in env:
            roots |= env["pmk.org"].sudo().with_context(active_test=False).search([]).partner_id
        ids = set(Partner.search([("id", "child_of", roots.ids)]).ids) if roots else set()
        ids |= set(env["res.users"].sudo().with_context(active_test=False).search([]).partner_id.ids)
        return ids

    @api.model
    def _pmk_own_inns(self):
        own = self.sudo().with_context(active_test=False).browse(self._pmk_own_partner_ids())
        return {inn for inn in map(partner_keys.inn_of, own.mapped("vat")) if inn}

    @api.model
    def _pmk_own_domains(self):
        """Домены своих организаций: почта и сайт карточек компаний и
        «Наших организаций». Общие (mail.ru) отсеются и так."""
        env = self.env
        roots = env["res.company"].sudo().search([]).partner_id
        if "pmk.org" in env:
            roots |= env["pmk.org"].sudo().with_context(active_test=False).search([]).partner_id
        domains = set()
        for partner in roots:
            domains |= partner_keys.email_domains(partner.email)
            site = partner_keys.site_domain(partner.website)
            if site:
                domains.add(site)
        for company in env["res.company"].sudo().search([]):
            domains |= partner_keys.email_domains(company.email)
        return domains

    @api.model
    def _pmk_public_domains(self):
        extra = self.env["ir.config_parameter"].sudo().get_param(PUBLIC_DOMAINS_PARAM, "")
        return partner_keys.public_domains(extra)

    def _pmk_domains(self):
        """Корпоративные (не общие) и не свои домены карточки: почта, сайт,
        почта для прайсов (pmk_purchase, если стоит)."""
        domains = set()
        has_price = "pmk_price_email" in self._fields
        for partner in self:
            domains |= partner_keys.email_domains(partner.email)
            if has_price:
                domains |= partner_keys.email_domains(partner.pmk_price_email)
            site = partner_keys.site_domain(partner.website)
            if site:
                domains.add(site)
        return domains

    # ------------------------------------------------------------------
    # поиск клиента
    # ------------------------------------------------------------------
    @api.model
    def _pmk_find_company(self, email=None, inns=(), exclude_domains=(), text=None):
        """Клиент-компания по ИНН из письма или по домену адреса.

        email — адрес отправителя; inns — ИНН, уже найденные вызывающим;
        text — текст письма, ИНН в нём («ИНН 2721…») ищется здесь же;
        exclude_domains — домены (или хосты), которые не связывают: например,
        ящики «Почты» завода.
        -> {"partners": res.partner, "how": "inn" | "domain" | False,
            "key": ИНН или домен, "archived": все найденные в архиве}
        Найден один — клиент; несколько — выбирать человеку."""
        result = {"partners": self.browse(), "how": False, "key": False, "archived": False}
        inns = list(inns or ()) + partner_keys.inns_in(text)
        own = self._pmk_own_partner_ids()
        Partner = self.with_context(active_test=False)

        def companies(found):
            found = found.commercial_partner_id.filtered(
                lambda p: p.is_company and p.id not in own)
            active = found.filtered("active")
            return (active or found), not active and bool(found)

        own_inns = self._pmk_own_inns()
        for inn in inns:
            if not partner_keys.inn_valid(inn) or inn in own_inns:
                continue
            found = Partner.search([("vat", "in", [inn, "RU" + inn])])
            partners, archived = companies(found)
            if partners:
                result.update(partners=partners, how="inn", key=inn, archived=archived)
                return result

        domain = partner_keys.email_domain(email)
        skip = self._pmk_public_domains() | self._pmk_own_domains()
        skip |= {partner_keys.registrable_domain(item) for item in exclude_domains or ()}
        if not domain or domain in skip:
            return result
        search = ["|", ("email", "ilike", domain), ("website", "ilike", domain)]
        if "pmk_price_email" in self._fields:
            search = ["|", ("pmk_price_email", "ilike", domain)] + search
        # Подстрока ловит и «nottruboproduct.ru» — точное равенство домена
        # проверяем после поиска.
        candidates = Partner.search(search).filtered(
            lambda p: domain in p._pmk_domains())
        partners, archived = companies(candidates)
        if partners:
            result.update(partners=partners, how="domain", key=domain, archived=archived)
        return result

    @api.model
    def _pmk_match_text(self, match):
        """Подпись находки для людей: «Клиент найден по домену x.ru: Имя»."""
        partners = match.get("partners") or self.browse()
        if not partners:
            return ""
        how = "по ИНН %s" % match["key"] if match["how"] == "inn" else "по домену %s" % match["key"]
        names = ", ".join(partners.mapped("display_name"))
        if len(partners) > 1:
            return "%s подходят несколько клиентов: %s — выберите клиента" % (
                ("По ИНН %s" % match["key"]) if match["how"] == "inn" else ("По домену %s" % match["key"]),
                names)
        text = "Клиент найден %s: %s" % (how, names)
        if match.get("archived"):
            text += " (карточка в архиве)"
        return text
