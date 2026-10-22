# -*- coding: utf-8 -*-
"""Поступление денег на наш счёт: кто, сколько, за какой счёт.

Сопоставление (tools/match.py): переводы между своими счетами (ИНН плательщика
= ИНН нашей организации) — не поступление, в группу не идут. Клиент — по ИНН.
Счёт покупателю — номер из назначения + ИНН клиента + сумма. Счета из
МоегоСклада бот не отмечает: показывает, отметку в МС делает человек
(«сначала наблюдать», решение Антона). Счёт, сделанный в Odoo, оплата отмечает
сама (Антон 22.10.2026, этап 5 «сделка → счёт»): sale.order._pmk_bank_paid
(pmk_orders) — сумма к «Оплачено по банку», сделка в «Оплачено / в работе».
"""
import json
import logging
from datetime import datetime

from odoo import api, fields, models

from ..tools import match
from ..tools.message import payment_text
from ..tools.moysklad_print import MoySkladPrint, PrintError

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
    # Одна платёжка за несколько счетов («по счету №00683, №733, №832»): все
    # найденные счета, первый — sale_order_id.
    sale_order_ids = fields.Many2many("sale.order", string="Счета в платеже")
    state = fields.Selection(STATES, "Состояние", default="new", required=True)
    notified_at = fields.Datetime("Отправлено")
    note = fields.Char("Заметка")
    raw = fields.Text("Ответ банка")

    _ext_uniq = models.Constraint("UNIQUE(account_id, ext_id)", "Операция уже записана.")

    # ── из банка ─────────────────────────────────────────────────────────

    @api.model
    def _pmk_create_from_op(self, account, op, baseline=False):
        """op — операция в общем виде (tools/modulbank._norm, tools/tochka)."""
        pay = self.create({
            "account_id": account.id,
            "ext_id": op["id"],
            "executed": op.get("executed") or False,
            "amount": op.get("amount") or 0.0,
            "currency": op.get("currency"),
            "payer_name": op.get("payer_name"),
            "payer_inn": op.get("payer_inn"),
            "purpose": op.get("purpose"),
            "doc_number": op.get("doc_number"),
            "raw": json.dumps(op.get("raw") or op, ensure_ascii=False),
            "state": "baseline" if baseline else "new",
        })
        pay._pmk_match()
        if not baseline:
            pay._pmk_apply_to_orders()
        return pay

    def _pmk_label(self):
        self.ensure_one()
        bank = dict(self.account_id._fields["bank"].selection).get(self.account_id.bank, "банк")
        return "%s, п/п %s" % (bank, self.doc_number) if self.doc_number else bank

    def _pmk_apply_to_orders(self):
        """Счёт, сделанный в Odoo, — оплачен этим поступлением (pmk_orders: _pmk_bank_paid). Один
        счёт в платёжке — вся сумма ему; несколько — каждому его сумма, если платёж их покрывает,
        иначе — заметка: разнести руками. Сбой не мешает записать поступление."""
        for pay in self.filtered(lambda p: p.state == "new" and p.sale_order_ids):
            orders = pay.sale_order_ids.sudo()
            if not hasattr(orders, "_pmk_bank_paid"):
                continue
            orders = orders.filtered(lambda o: o._pmk_is_odoo_invoice())
            if not orders:
                continue
            if len(pay.sale_order_ids) == 1:
                shares = [(orders, pay.amount)]
            elif pay.amount + 1 >= sum(pay.sale_order_ids.mapped("amount_total")):
                shares = [(order, order.amount_total) for order in orders]
            else:
                pay.note = "несколько счетов, сумма меньше их итога — оплату отметьте руками"
                continue
            try:
                with self.env.cr.savepoint():
                    for order, amount in shares:
                        order._pmk_bank_paid(amount, pay.executed, pay._pmk_label())
            except Exception:  # noqa: BLE001 — поступление важнее отметки
                _logger.exception("Поступление %s: отметка оплаты счёта не вышла", pay.id)
                pay.note = "оплату в счёте отметить не вышло — отметьте руками"

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
            orders = pay._pmk_find_orders()
            order = orders[:1]
            pay.write({"partner_id": (order.partner_id.commercial_partner_id or partner).id,
                       "sale_order_id": order.id, "sale_order_ids": [(6, 0, orders.ids)]})

    def _pmk_find_order(self):
        return self._pmk_find_orders()[:1]

    def _pmk_find_orders(self):
        """Счета покупателю из назначения: по одному на номер (ИНН, сумма, дата).

        Один номер — выбор по ИНН, потом по сумме платежа. Несколько номеров —
        каждый номер отдельно по ИНН и дате (сумма платежа к одному счёту
        тут не относится), порядок — как в назначении.
        """
        self.ensure_one()
        numbers = match.invoice_numbers(self.purpose)
        Order = self.env["sale.order"]
        if not numbers or not self.payer_inn:
            return Order
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
        pool = same_org or rows
        inv_date = match.invoice_date(self.purpose)
        found = Order
        for number in numbers:
            candidates = [{"id": r[0], "amount": float(r[2] or 0), "date": r[3], "inn": r[4]}
                          for r in pool if r[1] == number]
            # Сумма платежа подсказывает только когда счёт один.
            amount = self.amount if len(numbers) == 1 else -1
            best = match.choose_invoice(candidates, self.payer_inn, amount, inv_date)
            if best:
                found |= Order.browse(best["id"])
        return found

    # ── уведомление ──────────────────────────────────────────────────────

    def _pmk_message(self, test=False):
        self.ensure_one()
        order = self.sale_order_id
        orders = self.sale_order_ids or order
        invoice = None
        if len(orders) > 1:
            # Платёж за несколько счетов: сравниваем с их общей суммой.
            missing = [n for n in match.invoice_numbers(self.purpose)
                       if n not in {match.norm_number(o.name) for o in orders}]
            invoice = {"names": orders.mapped("name"), "total": sum(orders.mapped("amount_total")),
                       "paid": self.amount, "missing": missing}
        elif order:
            paid = sum(self.search([("sale_order_id", "=", order.id),
                                    ("state", "!=", "internal")]).mapped("amount"))
            others = [n for n in match.invoice_numbers(self.purpose)
                      if n != match.norm_number(order.name)]
            invoice = {"name": order.name, "date": order.date_order and order.date_order.date(),
                       "total": order.amount_total, "paid": paid, "others": others}
        text = payment_text({
            "amount": self.amount,
            "payer": self.partner_id.name or self.payer_name or "плательщик не указан",
            "payer_inn": self.payer_inn,
            "purpose": self.purpose,
            "date": self.executed or datetime.now().date(),
            "org": self.account_id.org_id.name,
            "doc_number": self.doc_number,
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

    def _pmk_invoice_pdfs(self):
        """PDF счетов этого поступления из МоегоСклада: [(имя, байты)].

        Первым — основной счёт, дальше остальные из той же платёжки (решение
        Антона 14.10.2026: прикреплять все). Счёт без id МоегоСклада, нет
        ключа, МойСклад не ответил — просто без файла: уведомление о деньгах
        важнее вложения.
        """
        self.ensure_one()
        orders = (self.sale_order_id | self.sale_order_ids)
        if not orders or "pmk_ms_id" not in orders._fields:
            return []
        token = self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.token")
        if not token:
            return []
        printer = MoySkladPrint(token, self.env["ir.config_parameter"].sudo().get_param(
            "pmk_bank.ms_template") or "Счет №")
        files = []
        for order in orders:
            if not order.pmk_ms_id:
                continue
            try:
                files.append(("Счёт %s.pdf" % order.name, printer.invoice_pdf(order.pmk_ms_id)))
            except PrintError as exc:
                _logger.warning("Поступление %s: счёт %s без PDF — %s", self.id, order.name, exc)
        return files

    def pmk_notify(self, test=False):
        bot = self.env["pmk.telegram.bot"].sudo()
        for pay in self:
            text, markup = pay._pmk_message(test=test)
            ok = bot.pmk_send_group_files(text, pay._pmk_invoice_pdfs(), markup, kind="money")
            if test:
                continue
            pay.write({"state": "notified" if ok else "failed",
                       "notified_at": fields.Datetime.now() if ok else False,
                       "note": False if ok else "группа не подключена или Телеграм не принял"})
