# -*- coding: utf-8 -*-
"""«Выиграно» с формы сделки — короткое окно «Оплата / гарантия» (шаг З-15).

Решение Антона 08.10.2026: «Выиграно» = пришла предоплата или гарантийное
письмо. Окно спрашивает то, что раньше вносили в строку «Заказов в работе»
руками: «Сумму оплаты» (пусто = не вносили; под ней — «% от счёта» и сумма
счёта), «Дату оплаты» (сегодня) и галочку «Гарантийное письмо» вместо оплаты.
Подписи — как в строке «Заказов в работе»: одно понятие — одно слово.

  «Готово»     — сделка выиграна (штатный путь: счёт в работу, строка
                 планировщика, праздничная анимация), значения — в строку,
                 заметкой — в ленту сделки и счёта;
  «Пропустить» — сделка выиграна, строка без оплаты (как раньше);
  «Отмена» и крестик — ничего не происходит, сделка в работе.

Ничего не запрещает: сумма больше счёта — подсказка, не ошибка. Единственный
отказ — отрицательная сумма. Писем нет.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.project_task import date_text


class PmkOrdersWonWizard(models.TransientModel):
    _name = "pmk.orders.won.wizard"
    _description = "Выиграно: оплата или гарантийное письмо"

    lead_id = fields.Many2one("crm.lead", "Сделка", required=True, ondelete="cascade")
    currency_id = fields.Many2one("res.currency", "Валюта", compute="_compute_base")
    base_amount = fields.Monetary(
        "Сумма счёта", currency_field="currency_id", compute="_compute_base")
    amount = fields.Monetary(
        "Сумма оплаты", currency_field="currency_id",
        help="Сколько пришло. 0 — не вносили (внесёте в строке «Заказов в работе» потом).")
    date = fields.Date(
        "Дата оплаты", required=True, default=fields.Date.context_today,
        help="Когда пришла оплата, а при гарантийном письме — дата письма. От неё "
             "считается срок «с момента оплаты».")
    guarantee = fields.Boolean(
        "Гарантийное письмо (вместо оплаты)",
        help="Работу начинаем по гарантийному письму: срок — от его даты.")
    pct_hint = fields.Char("Доля счёта", compute="_compute_hints")
    due_hint = fields.Char("Срок", compute="_compute_hints")

    def _pmk_invoice(self):
        self.ensure_one()
        return self.lead_id._pmk_current_invoice() if self.lead_id else self.env["sale.order"]

    @api.depends("lead_id")
    def _compute_base(self):
        for wizard in self:
            lead = wizard.lead_id.sudo()
            invoice = wizard._pmk_invoice()
            wizard.currency_id = (invoice.currency_id or lead.company_id.currency_id
                                  or self.env.company.currency_id)
            wizard.base_amount = invoice.amount_total if invoice else lead.expected_revenue

    @api.depends("lead_id", "amount", "date", "guarantee")
    def _compute_hints(self):
        Task = self.env["project.task"]
        for wizard in self:
            lead = wizard.lead_id.sudo()
            invoice = wizard._pmk_invoice()
            base = wizard.base_amount
            total = lead._pmk_money(base, wizard.currency_id) if base else ""
            if wizard.amount > 0 and base:
                pct = round(wizard.amount / base * 100.0)
                of = (_("от счёта %(invoice)s (%(total)s)", invoice=invoice.display_name,
                        total=total) if invoice else _("от суммы сделки (%s)", total))
                hint = "%s %% %s" % (pct, of)
                if wizard.amount > base:
                    hint += " — " + _("больше суммы счёта, проверьте")
            elif invoice:
                hint = _("Счёт %(invoice)s: %(total)s", invoice=invoice.display_name,
                         total=total or lead._pmk_money(0.0, wizard.currency_id))
                if invoice.pmk_payment_note:
                    hint += " · " + invoice.pmk_payment_note
            elif base:
                hint = _("Счёта у сделки нет — сумма сделки %s", total)
            else:
                hint = _("Счёта у сделки нет")
            wizard.pct_hint = hint
            wizard.due_hint = wizard._pmk_due_hint(Task, invoice)

    def _pmk_due_hint(self, Task, invoice):
        self.ensure_one()
        if not invoice:
            return _("Сдача (план) — руками в строке «Заказов в работе»: счёта нет.")
        days = invoice.pmk_lead_days or 0
        if days <= 0:
            return _("В счёте не указан срок изготовления — «Сдача (план)» руками.")
        lead = invoice.pmk_lead_text or ""
        if invoice.pmk_lead_from == "drawings":
            return _("Срок «%s» — дату сдачи поставите, когда согласуют чертежи.", lead)
        if invoice.pmk_lead_from == "invoice":
            start = Task._pmk_invoice_day(invoice)
        elif (self.amount > 0 or self.guarantee) and self.date:
            start = self.date
        else:
            start = fields.Date.context_today(self)
        due = Task._pmk_add_work_days(start, days, invoice.company_id)
        if not due:
            return False
        return _("Сдача (план): %(due)s — %(lead)s, отсчёт от %(start)s.",
                 due=date_text(due), lead=lead, start=date_text(start))

    # ─── Кнопки ─────────────────────────────────────────────────────────
    def action_done(self):
        self.ensure_one()
        if self.amount < 0:
            raise UserError(_("Сумма оплаты не может быть меньше нуля. Не пришла — оставьте 0 "
                              "или нажмите «Пропустить»."))
        lead = self.lead_id
        # До копеек: «0,0025» (опечатка, дописали к «0,00») — «не вносили»,
        # а не оплата «0,00 руб» в ленте.
        amount = self.currency_id.round(self.amount) if self.currency_id else round(self.amount, 2)
        result = lead.action_set_won_rainbowman()
        if amount > 0 or self.guarantee:
            lead._pmk_orders_safely(
                "_pmk_won_payment", amount, self.date or fields.Date.context_today(self),
                self.guarantee)
        return self._pmk_close(result)

    def action_skip(self):
        self.ensure_one()
        return self._pmk_close(self.lead_id.action_set_won_rainbowman())

    @api.model
    def _pmk_close(self, result):
        """Закрыть окно; праздничную анимацию штатной кнопки — показать."""
        action = {"type": "ir.actions.act_window_close"}
        if isinstance(result, dict) and result.get("effect"):
            action["effect"] = result["effect"]
        return action
