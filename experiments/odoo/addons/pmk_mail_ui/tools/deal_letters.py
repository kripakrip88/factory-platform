# -*- coding: utf-8 -*-
"""Письма клиента для вкладки «Письма» сделки (15.10.2026) — чистые правила.

Антон 15.10: «встроить отображение вообще всех писем отправителя, чтоб
допривязать к сделке доп. письма, если вдруг в письме затёрли тему». Письмо
клиента узнаём по адресу (контакт сделки, все контакты его компании) и по
домену компании — кроме общих почтовых служб (mail.ru, gmail.com…): там домен
ничего не говорит о компании, и «все письма с @mail.ru» — это весь ящик.

Без Odoo: проверяется голым питоном (tests/test_deal_letters_rules.py).
"""
import re

# Свой список — если pmk_partner не стоит (у него тот же список и системный
# параметр pmk_partner.public_mail_domains, его берёт модель).
PUBLIC_MAIL_DOMAINS = frozenset({
    "mail.ru", "bk.ru", "list.ru", "inbox.ru", "internet.ru", "xmail.ru",
    "gmail.com", "googlemail.com",
    "yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.ua", "ya.ru",
    "narod.ru", "rambler.ru", "ro.ru", "autorambler.ru", "myrambler.ru", "lenta.ru",
    "icloud.com", "me.com", "mac.com",
    "outlook.com", "hotmail.com", "live.com", "live.ru", "msn.com",
    "yahoo.com", "mail.com", "aol.com", "gmx.com", "gmx.de",
    "vk.com", "proton.me", "protonmail.com", "tutanota.com",
    "ngs.ru", "e1.ru", "redcom.ru", "qip.ru", "pochta.ru",
})

SECOND_LEVEL_SUFFIXES = frozenset({
    "com.ru", "net.ru", "org.ru", "pp.ru", "msk.ru", "spb.ru", "khv.ru",
    "msk.su", "spb.su", "co.uk", "com.cn", "com.kz", "org.kz",
})

_ADDRESS = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def addresses(*texts):
    """Все адреса из строк «Имя <a@b.ru>, c@d.ru» — строчными, без повторов."""
    found = []
    for text in texts:
        for item in _ADDRESS.findall(text or ""):
            item = item.lower().strip(".")
            if item not in found:
                found.append(item)
    return found


def registrable_domain(host):
    """«mail.redcom.ru» → «redcom.ru», «shop.com.ru» → «shop.com.ru»."""
    labels = [label for label in (host or "").strip().lower().strip(".").split(".") if label]
    if len(labels) < 2:
        return ""
    tail = ".".join(labels[-2:])
    if tail in SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:]) if len(labels) >= 3 else ""
    return tail


def domain_of(address):
    return registrable_domain((address or "").rsplit("@", 1)[-1]) if "@" in (address or "") else ""


def client_keys(emails, own_addresses=(), public=PUBLIC_MAIL_DOMAINS):
    """(адреса клиента, домены клиента) из адресов карточек.

    Свои адреса и домены (ящики завода) — не клиент: письмо с pmkpark@ есть в
    каждой переписке. Домен общей почтовой службы — не ключ, только адрес.
    """
    own = set(addresses(*own_addresses))
    own_domains = {domain_of(item) for item in own} - {""}
    mails = [item for item in addresses(*emails) if item not in own]
    domains = []
    for item in mails:
        domain = domain_of(item)
        if domain and domain not in public and domain not in own_domains and domain not in domains:
            domains.append(domain)
    return mails, domains


def match_reason(letter_addresses, mails, domains):
    """Почему письмо — клиента: 'address' (адрес контакта), 'domain' (домен
    компании) или None."""
    mails, domains = set(mails), set(domains)
    if any(item in mails for item in letter_addresses):
        return "address"
    if domains and any(domain_of(item) in domains for item in letter_addresses):
        return "domain"
    return None
