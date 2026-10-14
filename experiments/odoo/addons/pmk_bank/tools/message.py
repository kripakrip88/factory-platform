# -*- coding: utf-8 -*-
"""Текст уведомления о поступлении (HTML Телеграма). Чистая функция.

Шаблон — вариант A, выбранный Антоном 14.10.2026: сумма и клиент крупно,
на какую из наших организаций пришли деньги, счёт и его оплата значком,
«за что» одной строкой; назначение целиком, ИНН, номер платёжки и дата —
в свёрнутом блоке (раскрывается нажатием). Расчётный счёт не пишем.
"""
import html
import re

from .match import money

PURPOSE_MAX = 300
WHAT_MAX = 80

# «… ЗА СНЕГОЗАДЕРЖАТЕЛЬ НА СУММУ 11500, В Т.Ч. НДС …» → «снегозадержатель»
_WHAT_RE = re.compile(r"(?<![а-яё])за\s+(.+)", re.IGNORECASE)
_WHAT_STOP = re.compile(
    r"(\s+на\s+сумму|\s*сумма\b|[,;]?\s*в\s*т\.?\s*ч\.?|\s*в\s+том\s+числе|\s*ндс\b|\s*без\s+ндс|"
    r"[,;]\s*\d|\s+\d[\d\s]*[-.,]\d{2}\s*руб|\s+-\s*\d[\d\s]*[-.,]\d{2}\b)",
    re.IGNORECASE)


def _esc(text):
    return html.escape(text or "", quote=False)


def what_for(purpose):
    """«За что» из назначения платежа или "" — если клиент не написал."""
    m = _WHAT_RE.search(purpose or "")
    if not m:
        return ""
    text = _WHAT_STOP.split(m.group(1), maxsplit=1)[0].strip(" .,;-–—")
    if len(text) < 3:
        return ""
    # Капсом клиенты пишут всё подряд: слова — строчными, а короткие
    # сокращения (ТМЦ, КМД, ПВЛ…) — как есть.
    words = []
    for w in text.split(" "):
        letters = re.sub(r"[^А-Яа-яЁёA-Za-z]", "", w)
        keep = letters.isupper() and len(letters) <= 3 and letters not in ("ЭЛ", "ШТ", "ЗА", "НА")
        words.append(w if keep else w.lower())
    text = " ".join(words)
    return text if len(text) <= WHAT_MAX else text[:WHAT_MAX - 1].rstrip() + "…"


def org_short(name):
    """«ИП Чулков Владислав Витальевич» → «ИП Чулков»; ООО — как есть."""
    parts = (name or "").split()
    if len(parts) >= 2 and parts[0].upper() == "ИП":
        return "ИП " + parts[1]
    return name or ""


def _bar(pct):
    n = max(0, min(10, round(pct / 10)))
    return "▓" * n + "░" * (10 - n)


def payment_text(p, test=False):
    """p — словарь поступления:
        amount, payer (имя для показа), payer_inn, purpose, date (date), org,
        doc_number, invoice: None | {name, date, total, paid}, partner_known.
    """
    lines = []
    if test:
        lines.append("<i>ТЕСТ — проверка модуля, не новое поступление</i>")
    lines.append("<b>💰 %s</b>" % _esc(money(p["amount"])))
    lines.append("<b>%s</b>" % _esc(p["payer"]))
    lines.append("🏦 на %s" % _esc(org_short(p.get("org"))))
    lines.append("")
    inv = p.get("invoice")
    if inv:
        when = " от %s" % inv["date"].strftime("%d.%m") if inv.get("date") else ""
        lines.append("🧾 Счёт <b>%s</b>%s" % (_esc(inv["name"]), when))
        total, paid = inv["total"] or 0, inv["paid"] or 0
        if total and paid >= total - 0.005:
            lines.append("✅ Оплачен полностью" if paid <= total + 0.005
                         else "✅ Оплачен, переплата %s" % _esc(money(paid - total)))
        elif total:
            pct = paid * 100 / total
            lines.append("🟡 Оплачено %d%% из %s" % (round(pct), _esc(money(total))))
            lines.append(_bar(pct))
    elif p.get("partner_known"):
        lines.append("❓ Счёт не определён — клиент есть в Odoo")
    else:
        lines.append("❓ Счёт не определён — плательщика нет в Odoo")
    what = what_for(p.get("purpose"))
    if what:
        lines.append("")
        lines.append("📦 %s" % _esc(what))
    purpose = (p.get("purpose") or "").strip()
    if len(purpose) > PURPOSE_MAX:
        purpose = purpose[:PURPOSE_MAX - 1].rstrip() + "…"
    details = ["Назначение: %s" % _esc(purpose)]
    tail = ["ИНН %s" % _esc(p.get("payer_inn") or "—")]
    if p.get("doc_number"):
        tail.append("п/п №%s" % _esc(p["doc_number"]))
    tail.append(p["date"].strftime("%d.%m.%Y"))
    details.append(" · ".join(tail))
    lines.append("<blockquote expandable>%s</blockquote>" % "\n".join(details))
    return "\n".join(lines)
