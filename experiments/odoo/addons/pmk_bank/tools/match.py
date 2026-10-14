# -*- coding: utf-8 -*-
"""Поступление → счёт покупателю. Чистые функции, без Odoo — проверяются на
живых платежах до установки модуля (tests/test_match.py).

Как клиенты пишут назначение (живые платежи Модульбанка, 08–13.10.2026):
    «ОПЛАТА ПО СЧЕТУ 01183 ОТ 09.10.2026 ЗА СНЕГОЗАДЕРЖАТЕЛЬ…»
    «МСП Оплата 70% поставки … по счету№01155 от 06.10.2026»
    «Оплата по счету № 01166 от 07.10.2026 за …»
    «ОПЛАТА ПО СЧ 987 ОТ 24.08.2026Г. ЗА ДОБОРНЫЙ ЭЛ. …»
    «Оплата счета № 01113 от 24.09.2026 г. за лазерную резку»

Номера счетов в Odoo (из МоегоСклада) повторяются по годам: «01183» этого
года и «001183» прошлого — у разных клиентов. Поэтому номер сравнивается без
ведущих нулей, а выбор среди одинаковых номеров — по ИНН плательщика, потом
по сумме, потом по свежести.
"""
import re
from datetime import date

# «счет/счёт/счету/счета/сч/сч.» → необязательные «№», «N», пробелы → номер.
_INVOICE_RE = re.compile(
    r"(?<![а-яё])(?:сч[её]т[а-яё]*|сч\.?)\s*(?:№|N|#)?\s*(?:№\s*)?(\d{2,7})",
    re.IGNORECASE)
_DATE_RE = re.compile(r"от\s+(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", re.IGNORECASE)


def norm_number(number):
    """«001183» и «01183» → «1183»; пусто — пусто."""
    return (number or "").strip().lstrip("0")


# Продолжение списка после первого номера: «по счету №00683, №733, №832»,
# «по сч. 1200 и 1201». Только сразу за номером — дальше уже не номера счетов.
_MORE_RE = re.compile(r"\s*(?:,|;|\bи\b)\s*(?:№|N)?\s*(\d{2,7})(?![\d.,]*\s*(?:руб|р\.|%|шт|кг|мм|см|п\.?\s*м|м\b|т\b|тн\b|л\b))",
                      re.IGNORECASE)


def invoice_numbers(purpose):
    """Номера счетов из назначения платежа, по порядку, без повторов."""
    text = purpose or ""
    seen, out = set(), []

    def add(raw):
        n = norm_number(raw)
        if n and n not in seen:
            seen.add(n)
            out.append(n)

    for m in _INVOICE_RE.finditer(text):
        add(m.group(1))
        pos = m.end()
        while True:
            more = _MORE_RE.match(text, pos)
            if not more:
                break
            add(more.group(1))
            pos = more.end()
    return out


def invoice_date(purpose):
    """Дата счёта из «… от 09.10.2026» (первая), иначе None."""
    m = _DATE_RE.search(purpose or "")
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def choose_invoice(candidates, payer_inn, amount, inv_date=None):
    """Лучший счёт среди кандидатов с подходящим номером.

    candidates — [{"id", "inn", "amount", "date"(date|None)}].
    Только счета этого плательщика (по ИНН); среди них — точная сумма, иначе
    ближайшая к дате из назначения, иначе самый свежий. Чужой ИНН — не
    подставляем: оплату за другого клиента лучше показать «без счёта», чем
    приписать не тому.
    """
    own = [c for c in candidates if payer_inn and c.get("inn") == payer_inn]
    if not own:
        return None
    exact = [c for c in own if abs((c.get("amount") or 0) - amount) < 0.005]
    pool = exact or own
    if inv_date:
        def gap(c):
            return abs((c["date"] - inv_date).days) if c.get("date") else 10 ** 6
        pool = sorted(pool, key=gap)
    else:
        pool = sorted(pool, key=lambda c: c.get("date") or date.min, reverse=True)
    return pool[0]


def money(value):
    """11500 → «11 500 ₽», 29509.6 → «29 509,60 ₽» (неразрывные пробелы)."""
    whole = abs(value) == int(abs(value))
    text = "{:,.0f}".format(value) if whole else "{:,.2f}".format(value)
    return text.replace(",", " ").replace(".", ",") + " ₽"


def paid_status(total, paid):
    """Строка о полноте оплаты счёта по сумме всех его поступлений."""
    if not total:
        return ""
    if paid >= total - 0.005:
        return "оплачен полностью" if paid <= total + 0.005 else "переплата %s" % money(paid - total)
    return "оплачено %s из %s (%d%%)" % (money(paid), money(total), round(paid * 100 / total))
