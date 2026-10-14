# -*- coding: utf-8 -*-
"""Текст уведомления о поступлении (HTML Телеграма). Чистая функция."""
import html

from .match import money, paid_status

PURPOSE_MAX = 160


def _esc(text):
    return html.escape(text or "", quote=False)


def payment_text(p, test=False):
    """p — словарь поступления:
        amount, payer (имя для показа), payer_inn, purpose, date (date), org,
        account_tail («8163»), invoice: None | {name, date, total, paid},
        partner_known (bool).
    """
    lines = []
    if test:
        lines.append("<i>ТЕСТ — проверка модуля, не новое поступление</i>")
    lines.append("💰 <b>+%s</b> — %s" % (_esc(money(p["amount"])), _esc(p["payer"])))
    inv = p.get("invoice")
    if inv:
        when = " от %s" % inv["date"].strftime("%d.%m.%Y") if inv.get("date") else ""
        lines.append("🧾 Счёт <b>%s</b>%s на %s → %s" % (
            _esc(inv["name"]), when, _esc(money(inv["total"])),
            _esc(paid_status(inv["total"], inv["paid"]))))
    elif p.get("partner_known"):
        lines.append("🧾 Счёт не определён — клиент есть в Odoo, разобрать вручную")
    else:
        lines.append("🧾 Счёт не определён — плательщика нет в Odoo")
    purpose = (p.get("purpose") or "").strip()
    if len(purpose) > PURPOSE_MAX:
        purpose = purpose[:PURPOSE_MAX - 1].rstrip() + "…"
    lines.append("<i>%s</i>" % _esc(purpose))
    lines.append("%s · ИНН %s · %s · р/с …%s" % (
        p["date"].strftime("%d.%m.%Y"), _esc(p.get("payer_inn") or "—"),
        _esc(p.get("org") or ""), _esc(p.get("account_tail") or "")))
    return "\n".join(lines)
