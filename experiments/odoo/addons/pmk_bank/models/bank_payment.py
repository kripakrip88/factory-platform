# -*- coding: utf-8 -*-
"""Поступление денег на наш счёт: кто, сколько, за какой счёт.

Сопоставление (tools/match.py): переводы между своими счетами (ИНН плательщика
= ИНН нашей организации) — не поступление, в группу не идут. Клиент — по ИНН.
Счёт покупателю — номер из назначения + ИНН клиента + сумма. Сам бот ничего
не отмечает оплаченным: показывает, а отметку делает человек
(«сначала наблюдать», решение Антона).
"""
import json
import logging
from datetime import datetime

from odoo import api, fields, models

from ..tools import match
from ..tools.message import payment_text

_logger = logging.getLogger(__name__)

STATES = [
    ("baseline", "Было до подключения"),
    ("internal", "Перевод между своими счетами"),
    ("new", "Новое"),
    ("notified", "Отправлено в группу"),
    ("failed", "Не отправлено"),
]
SALE_ACTION = "sale.action_quotations"


class PmkBankPayment(models.Model):
    _name = "pmk.bank.payment"
    _description = "Поступление на счёт"
    _order = "executed desc, id desc"

    account_id = fields.Many2one("pmk.bank.account", "Счёт", required=True, ondelete="cascade")
    org_id = fields.Many2one(related="account_id.org_id", store=True)
    ext_id = fields.Char("ID операции в банке", required=True, index=True)
    executed = fields.Date("Дата")
    amount = fields.Float("Сумма", digits=(16, 2))
    currency = fields.Char("Валюта")
    payer_name = fields.Char("Плательщик (банк)")
    payer_inn = fields.Char("ИНН плательщика", index=True)
    purpose = fields.Text("Назначение")
    doc_number = fields.Char("Номер платёжки")
    partner_id = fields.Many2one("res.partner", "Контрагент")
    sale_order_id = fields.Many2one("sale.order", "Счёт покупателю")
    state = fields.Selection(STATES, "Состояние", default="new", required=True)
    notified_at = fields.Datetime("Отправлено")
    note = fields.Char("Заметка")
    raw = fields.Text("Ответ банка")

    _ext_uniq = models.Constraint("UNIQUE(account_id, ext_id)", "Операция уже записана.")

    # ── из банка ─────────────────────────────────────────────────────────

    @api.model
    def _pmk_create_from_modulbank(self, account, op, baseline=False):
        executed = (op.get("executed") or op.get("created") or "")[:10]
        pay = self.create({
            "account_id": account.id,
            "ext_id": op.get("id"),
            "executed": executed or False,
            "amount": op.get("amount") or 0.0,
            "currency": op.get("currency"),
            "payer_name": op.get("contragentName"),
            "payer_inn": op.get("contragentInn"),
            "purpose": op.get("paymentPurpose"),
            "doc_number": op.get("docNumber"),
            "raw": json.dumps(op, ensure_ascii=False),
            "state": "baseline" if baseline else "new",
        })
        pay._pmk_match()
        return pay

    # ── сопоставление ────────────────────────────────────────────────────

    def _pmk_match(self):
        Partner = self.env["res.partner"].sudo()
        for pay in self:
            own_inn = pay.account_id.org_id.inn
            if pay.payer_inn and own_inn and pay.payer_inn == own_inn:
                pay.write({"state": "internal", "note": "перевод между своими счетами"})
                continue
            partner = Partner.search(
                [("vat", "=", pay.payer_inn), ("parent_id", "=", False)], limit=1
            ) if pay.payer_inn else Partner
            order = pay._pmk_find_order()
            pay.write({"partner_id": (order.partner_id.commercial_partner_id or partner).id,
                       "sale_order_id": order.id})

    def _pmk_find_order(self):
        """Счёт покупателю по номеру из назначения, ИНН и сумме (или пусто)."""
        self.ensure_one()
        numbers = match.invoice_numbers(self.purpose)
        if not numbers or not self.payer_inn:
            return self.env["sale.order"]
        self.env.cr.execute("""
            SELECT so.id, ltrim(so.name, '0'), so.amount_total, so.date_order::date,
                   cp.vat, so.pmk_org_id
              FROM sale_order so
              JOIN res_partner p ON p.id = so.partner_id
              JOIN res_partner cp ON cp.id = p.commercial_partner_id
             WHERE ltrim(so.name, '0') = ANY(%s) AND so.state != 'cancel'
        """, [numbers])
        rows = self.env.cr.fetchall()
        org = self.account_id.org_id.id
        same_org = [r for r in rows if r[5] == org]
        candidates = [{"id": r[0], "amount": float(r[2] or 0), "date": r[3], "inn": r[4]}
                      for r in (same_org or rows)]
        best = match.choose_invoice(candidates, self.payer_inn, self.amount,
                                    match.invoice_date(self.purpose))
        return self.env["sale.order"].browse(best["id"]) if best else self.env["sale.order"]

    # ── уведомление ──────────────────────────────────────────────────────

    def _pmk_message(self, test=False):
        self.ensure_one()
        order = self.sale_order_id
        invoice = None
        if order:
            paid = sum(self.search([("sale_order_id", "=", order.id),
                                    ("state", "!=", "internal")]).mapped("amount"))
            invoice = {"name": order.name, "date": order.date_order and order.date_order.date(),
                       "total": order.amount_total, "paid": paid}
        text = payment_text({
            "amount": self.amount,
            "payer": self.partner_id.name or self.payer_name or "плательщик не указан",
            "payer_inn": self.payer_inn,
            "purpose": self.purpose,
            "date": self.executed or datetime.now().date(),
            "org": self.account_id.org_id.name,
            "account_tail": (self.account_id.number or "")[-4:],
            "invoice": invoice,
            "partner_known": bool(self.partner_id),
        }, test=test)
        base = (self.env["ir.config_parameter"].sudo().get_param("web.base.url") or "").rstrip("/")
        row = []
        if base.startswith("https://"):
            if order:
                row.append({"text": "🧾 Открыть счёт",
                            "url": f"{base}/odoo/action-{SALE_ACTION}/{order.id}"})
            elif self.partner_id:
                row.append({"text": "👤 Контрагент", "url": f"{base}/odoo/contacts/{self.partner_id.id}"})
        return text, ({"inline_keyboard": [row]} if row else None)

    def pmk_notify(self, test=False):
        bot = self.env["pmk.telegram.bot"].sudo()
        for pay in self:
            text, markup = pay._pmk_message(test=test)
            ok = bot.pmk_send_group(text, markup, kind="money")
            if test:
                continue
            pay.write({"state": "notified" if ok else "failed",
                       "notified_at": fields.Datetime.now() if ok else False,
                       "note": False if ok else "группа не подключена или Телеграм не принял"})
