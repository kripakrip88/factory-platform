# -*- coding: utf-8 -*-
"""Расчёт → черновик счёта покупателю (разбор UX, шаг З-9, 09.10.2026).

Решение Антона 09.10.2026: «Счёт как таковой создаётся на этапе расчёта,
возможно меняется или дополняется», а отправляется, когда сформировали,
прописали условия и согласовали. Выбор Антона — черновик КНОПКОЙ «Счёт» в
расчёте (не сам и не стадией сделки).

КНОПКА «СЧЁТ» (action_pmk_invoice). Счёт — один на сделку:
  • счёта нет — черновик из этого расчёта (клиент, организация, сделка,
    изделия с ценой строками) — и открыть;
  • черновик этого расчёта — обновить из расчёта и открыть;
  • черновик другого расчёта той же сделки — переключить на этот (с
    заметкой), новый счёт не заводим;
  • отправлен или в работе — открыть его с подсказкой: изменения расчёта
    войдут как «ред. N» при «Отправить КП» (в работе — не войдут);
  • отменён у сделки в работе (восстановили после «Проиграно», отменили
    руками) — снова черновик; если отменённый уже уходил клиенту и расчёт с
    тех пор изменился — прежнее содержание сохраняется редакцией;
  • отменён у проигранной сделки — открыть с подсказкой.
Нет сделки или клиента — ошибка словами: документ без них не собрать.

ЧЕРНОВИК ИДЁТ ЗА РАСЧЁТОМ. Сохранили расчёт (состав, количество, цена,
клиент, организация) — строки-изделия черновиков с этим расчётом
пересобираются сами (_pmk_sync_draft_invoices): без редакций, услуги не
трогаются. Отправленный счёт не меняется — на нём плашка «расчёт изменился
после отправки», новая редакция — при «Отправить КП». Пересборка идёт через
sudo: расчёт правит и технолог без прав на счета. Сбой пересборки не роняет
сохранение расчёта: откат до точки сохранения и заметка в ленте счёта.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from .sale_order import SKIP, money_text

_logger = logging.getLogger(__name__)

# Контекст: изделия пишутся внутри записи расчёта — пересборка один раз, после.
SPEC_WRITING = "pmk_orders_spec_writing"
SPEC_FIELDS = frozenset({"product_ids", "partner_id", "pmk_org_id"})
PRODUCT_FIELDS = frozenset({"name", "qty", "price_customer_unit", "sequence", "spec_id"})


class MetalSpecInvoice(models.Model):
    _inherit = "pmk.metal.spec"

    def action_pmk_invoice(self):
        """Кнопка «Счёт» в расчёте — см. шапку файла."""
        self.ensure_one()
        spec = self
        deal = spec.opportunity_id
        if not deal:
            raise UserError(_(
                "Счёт покупателю — один на сделку: сначала укажите сделку в расчёте."))
        Order = self.env["sale.order"]
        if not Order.has_access("create"):
            raise UserError(_(
                "Заводить счета покупателям вам нельзя по правам — скажите руководителю."))
        partner = Order._pmk_invoice_partner(deal, spec)
        if not partner:
            raise UserError(_(
                "Укажите клиента в сделке или в расчёте — без него счёт не собрать."))
        org = spec.pmk_org_id or deal.pmk_org_id
        lead = deal.sudo().with_context(**{SKIP: True})
        invoice = lead._pmk_current_invoice()
        notify = None
        if not invoice:
            invoice = Order._pmk_create_from_spec(lead, spec, partner, org)
            text = _(
                "Черновик счёта покупателю %(invoice)s из расчёта %(spec)s: изделий %(count)s, "
                "сумма %(total)s. Отправленным он станет по «Отправить КП».",
                invoice=invoice.display_name, spec=spec.name,
                count=len(invoice.order_line.filtered("pmk_from_spec")),
                total=money_text(self.env, invoice.amount_total, invoice.currency_id))
            lead._pmk_orders_note(text)
            invoice._pmk_note(text)
        elif invoice.state == "draft":
            old = invoice.pmk_spec_id
            invoice._pmk_sync_from_spec(spec)
            if old != spec:
                text = _("Черновик счёта %(invoice)s переключён с расчёта %(old)s на %(spec)s.",
                         invoice=invoice.display_name, old=old.name or _("(нет)"),
                         spec=spec.name)
                lead._pmk_orders_note(text)
                invoice._pmk_note(text)
        elif invoice.state == "cancel" and deal.active and deal.won_status != "lost":
            invoice._pmk_reopen_draft(spec, partner, org)
            text = _("Счёт покупателю %(invoice)s снова «Черновик» — из расчёта %(spec)s.",
                     invoice=invoice.display_name, spec=spec.name)
            lead._pmk_orders_note(text)
            invoice._pmk_note(text)
        elif invoice.state == "cancel":
            notify = _("Сделка проиграна — счёт %s отменён. Чтобы вернуть его, восстановите "
                       "сделку.", invoice.display_name)
        elif invoice.state == "sale":
            notify = _("Счёт %s в работе (оплачен) — изменения расчёта в него не попадут.",
                       invoice.display_name)
        else:
            notify = _("Счёт %(invoice)s уже отправлен. Изменения расчёта войдут в него как "
                       "ред. %(next)s — по «Отправить КП».",
                       invoice=invoice.display_name, next=(invoice.pmk_revision or 1) + 1)
        return self._pmk_open_invoice(invoice, notify)

    def _pmk_open_invoice(self, invoice, notify=None):
        """Форма счёта; нет права читать (чужой счёт у продавца «только свои») —
        уведомление с номером."""
        mine = invoice.with_env(self.env)
        if not mine.has_access("read"):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Счёт покупателю"),
                    "message": _("Счёт сделки — %s; открыть его вам нельзя по правам.",
                                 invoice.sudo().display_name),
                    "type": "warning",
                    "sticky": False,
                },
            }
        action = mine._pmk_form_action()
        if not notify:
            return action
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Счёт покупателю"),
                "message": notify,
                "type": "info",
                "sticky": False,
                "next": action,
            },
        }

    # ─── Черновик идёт за расчётом ──────────────────────────────────────
    def write(self, vals):
        if self.env.context.get(SPEC_WRITING) or not (SPEC_FIELDS & set(vals)):
            return super().write(vals)
        res = super(MetalSpecInvoice, self.with_context(**{SPEC_WRITING: True})).write(vals)
        self._pmk_sync_draft_invoices()
        return res

    def _pmk_sync_draft_invoices(self):
        """Черновики счетов с этими расчётами — вслед за расчётом (без
        редакций). Отправленные, в работе, отменённые и снимки не трогаем."""
        specs = self.exists()
        if not specs:
            return
        orders = self.env["sale.order"].sudo().search([
            ("pmk_spec_id", "in", specs.ids), ("state", "=", "draft"),
            ("pmk_is_revision", "=", False)])
        for order in orders:
            try:
                with self.env.cr.savepoint():
                    order._pmk_sync_from_spec()
            except Exception as error:  # noqa: BLE001 — сохранение расчёта важнее
                _logger.exception("pmk_orders: черновик %s не обновился из расчёта", order.id)
                order._pmk_note(_(
                    "Черновик не обновился из расчёта %(spec)s (%(error)s): нажмите «Счёт» в "
                    "расчёте ещё раз или скажите администратору.",
                    spec=order.pmk_spec_id.name, error=str(error)))


class MetalSpecProductInvoice(models.Model):
    _inherit = "pmk.metal.spec.product"

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        if not self.env.context.get(SPEC_WRITING):
            products.spec_id._pmk_sync_draft_invoices()
        return products

    def write(self, vals):
        if self.env.context.get(SPEC_WRITING) or not (PRODUCT_FIELDS & set(vals)):
            return super().write(vals)
        specs = self.spec_id
        res = super().write(vals)
        (specs | self.spec_id)._pmk_sync_draft_invoices()
        return res

    def unlink(self):
        specs = self.spec_id
        res = super().unlink()
        if not self.env.context.get(SPEC_WRITING):
            specs._pmk_sync_draft_invoices()
        return res

