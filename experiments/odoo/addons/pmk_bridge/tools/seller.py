# -*- coding: utf-8 -*-
"""Кто выставляет КП: строки реквизитов и налога (разбор UX, шаг 58).

Чистые функции без базы — их гоняет голый питон
(python3 addons/pmk_bridge/tests/test_step58_seller.py), а печать КП
(report/quotation_report.xml) получает от модели уже готовые строки.

До шага 58 шаблон КП держал две зашитые вещи: ставку «НДС 22%» и подпись
«ОГРНИП» у регистрационного номера. Для ИП Чулкова это верно, для ООО на
УСН — ложь в документе клиенту. Теперь ставка — из налога или налогового
режима организации, подпись номера — из её типа (ООО → ОГРН, ИП → ОГРНИП).
"""

# Подписи регистрационного номера: у организации — ОГРН (13 цифр), у
# предпринимателя — ОГРНИП (15 цифр).
REG_LABELS = {"ooo": "ОГРН", "ip": "ОГРНИП"}

NO_VAT = "Без НДС"
NO_VAT_USN = "Без НДС (УСН)"


def org_type_by_inn(inn):
    """ИП или организация — по длине ИНН: 12 цифр у предпринимателя, 10 у
    организации. Пустой или кривой ИНН — организация (подпись «ОГРН»)."""
    digits = "".join(ch for ch in (inn or "") if ch.isdigit())
    return "ip" if len(digits) == 12 else "ooo"


def reg_label(org_type):
    """«ОГРН» или «ОГРНИП» по типу организации."""
    return REG_LABELS.get(org_type or "ooo", REG_LABELS["ooo"])


def rate_text(rate):
    """Ставка словами для печати: 22.0 → «22», 5.5 → «5,5»."""
    rate = float(rate or 0.0)
    if rate.is_integer():
        return "%d" % rate
    return ("%g" % rate).replace(".", ",")


def tax_line(rate, total, usn=False):
    """Строка налога под «Итого к оплате»: (подпись, сумма или None).

    Цена в КП уже с налогом, поэтому налог выделяется «в том числе», а не
    прибавляется: сумма = итог × ставка / (100 + ставка). Ставка 0 — налога
    нет вовсе: «Без НДС», у упрощёнки — «Без НДС (УСН)», суммы нет.
    """
    rate = float(rate or 0.0)
    if rate <= 0:
        return (NO_VAT_USN if usn else NO_VAT, None)
    return ("в том числе НДС %s%%:" % rate_text(rate), (total or 0.0) * rate / (100.0 + rate))


def short_fio(full_name):
    """«Чулков Владислав Витальевич» → «Чулков В. В.» — для строки подписи.

    Одно слово (или пусто) — как есть: инициалы из него не собрать.
    """
    parts = (full_name or "").split()
    if len(parts) < 2:
        return " ".join(parts)
    return "%s %s" % (parts[0], " ".join("%s." % p[0].upper() for p in parts[1:3]))


def address_line(legal_address, city, street):
    """Адрес в шапке: юридический одной строкой, иначе «город, улица»."""
    if legal_address and legal_address.strip():
        return " ".join(legal_address.split())
    return ", ".join(x for x in (city, street) if x)


def seller_info(name, inn=None, kpp=None, org_type=None, reg_number=None,
                address=None, phone=None, email=None, bank=None,
                signer_position=None, signer_name=None,
                accountant_name=None):
    """Всё, что КП печатает о продавце, одним словарём.

    bank — словарь acc / bank / bic / corr или None. Пустые значения —
    пустые строки: шаблон печатает только заполненное.
    """
    org_type = org_type or org_type_by_inn(inn)
    return {
        "name": name or "",
        "inn": inn or "",
        "kpp": kpp or "",
        "reg_label": reg_label(org_type),
        "reg_number": reg_number or "",
        "address": address or "",
        "phone": phone or "",
        "email": email or "",
        "bank": bank or None,
        # Подпись: «Должность ____ Фамилия И. О.». Подписанта нет — как до
        # шага 58: название организации и черта.
        "sign_position": (signer_position or "") if signer_name else (name or ""),
        "sign_name": short_fio(signer_name) if signer_name else "",
        "accountant_name": short_fio(accountant_name) if accountant_name else "",
    }
