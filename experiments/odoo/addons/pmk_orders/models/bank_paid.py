# -*- coding: utf-8 -*-
"""Оплата счёта Odoo — от банка (Антон 22.10.2026, этап 5 плана «сделка → счёт»: «отметка оплаты —
от банка, в МС статус „Оплачен“ ставит Владимир вручную»; «да, пусть пока что так всё и будет»).

Поступление (pmk_bank) нашло счёт покупателю по номеру в назначении, ИНН и сумме. Если это счёт,
сделанный в Odoo (не из МоегоСклада — у тех оплату ведёт МС), то:
  • сумма прибавляется к «Оплачено по банку» счёта (частичные оплаты складываются);
  • сделка — в «Оплачено / в работе», если ещё не там: тем же путём, что ручная смена стадии
    (счёт подтверждается, строка «Заказов в работе»);
  • сумма и дата оплаты — в строку «Заказов в работе» (как окно «Оплата / гарантия»), запись в ленту
    счёта.
Счета МоегоСклада не трогаем: их статус «Оплачен» ставит Владимир в МС, сюда он приходит синхронизацией.
"""
from odoo import _, fields, models

STAGE_IN_WORK = "pmk_deal.stage_in_work"


class SaleOrderBankPaid(models.Model):
    _inherit = "sale.order"

    pmk_bank_paid = fields.Monetary("Оплачено по банку", copy=False, readonly=True,
                                    help="Сумма поступлений по этому счёту из банка (счета, сделанные в Odoo).")

    def _pmk_is_odoo_invoice(self):
        self.ensure_one()
        # Сделан в Odoo — нет id МС или он выгружен из Odoo (pmk_moysklad, этап 6: pmk_ms_from_odoo).
        from_ms = "pmk_ms_id" in self._fields and self.pmk_ms_id and not self["pmk_ms_from_odoo"]
        return not from_ms and not self.pmk_is_revision

    def _pmk_bank_paid(self, amount, day, label):
        """Поступление amount от day (label — «Модульбанк, п/п 123») по этому счёту. True — отмечено."""
        self.ensure_one()
        order = self.sudo()
        if not order._pmk_is_odoo_invoice() or order.state == "cancel" or amount <= 0:
            return False
        day = day or fields.Date.context_today(self)
        order.pmk_bank_paid += amount
        lead = order.opportunity_id

        def rub(value):
            return lead._pmk_money(value, order.currency_id) if lead else "%.2f" % value
        order.message_post(body=_("Оплата по банку: %(money)s от %(day)s (%(label)s). Всего оплачено по "
                                  "банку: %(total)s из %(invoice)s.",
                                  money=rub(amount), day=day.strftime("%d.%m.%Y"), label=label,
                                  total=rub(order.pmk_bank_paid), invoice=rub(order.amount_total)))
        if not lead:
            return True
        in_work = self.env.ref(STAGE_IN_WORK, raise_if_not_found=False)
        if in_work and lead.active and not lead.stage_id.is_won and lead.stage_id != in_work \
                and getattr(lead, "won_status", "") != "lost":
            lead._pmk_doc_stage(STAGE_IN_WORK)
        lead._pmk_orders_safely("_pmk_won_payment", order.pmk_bank_paid, day, False)
        return True
