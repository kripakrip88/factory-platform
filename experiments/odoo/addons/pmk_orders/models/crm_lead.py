# -*- coding: utf-8 -*-
"""Сделка ↔ счёт покупателю ↔ строка планировщика (разбор UX, шаг З-2).

Решения Антона 08.10.2026 (карточка 2 «Заказ от заявки до цеха»):

  «КП отправлено» (кнопка «Отправить КП» или перетаскивание в воронке) —
      из расчёта сделки выставляется «Счёт покупателю» в состоянии
      «Выставлен, ждём оплату». Расчёт — тот, КП которого ушло клиенту
      (путь «Отправить КП», kp_sent.py). Перетаскивание и «Выиграно» расчёта
      не знают: счёт уже есть — его же расчёт (тот, по которому счёт
      выставлен, если расчёт всё ещё этой сделки), счёта нет — главный
      расчёт сделки (pmk_spec_id). Иначе новый черновик-вариант, ставший
      главным, тихо переписал бы счёт тем, что клиенту не уходило. Выставить
      счёт по другому расчёту — «Отправить КП» из него. Счёт уже есть и расчёт с тех пор поменялся (состав,
      количество, цены, клиент, организация) — новая редакция того же счёта
      (sale_order.py). Не поменялся — тот же счёт, отменённый снова
      «Выставлен».
  «Выиграно» = пришла предоплата или гарантийное письмо — счёт
      подтверждается (складских документов нет: товар-услуга) и появляется
      РОВНО ОДНА строка «Заказов в работе» в «Очереди». Счёта ещё нет —
      сначала выставляем; не вышло — строка всё равно появляется.
  «Проиграно» — действующий счёт отменяется. Строка планировщика, если была,
      остаётся.

СИГНАЛ, А НЕ ЗАПРЕТ. Нет расчёта, цены или клиента — счёта нет, стадия
меняется как обычно, в ленте сделки — заметка, почему. Изделия без цены в
счёт не идут (как и в печать КП) и перечислены в заметке. Сбой нашего кода
не роняет сохранение сделки: откат до точки сохранения, заметка в ленте,
ошибка в журнал.

ГДЕ ЛОВИМ. write() сделки после штатного: сюда приходят кнопки «Выиграно» и
«Проиграно» (action_set_won / action_set_lost), перетаскивание в канбане,
правка в списке и переход по отправке КП (pmk_deal, _pmk_kp_move_stage).
Контекст pmk_orders_skip — свои записи без второго круга.
"""
import logging

from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models

from odoo.addons.pmk_deal.models.kp_sent import KP_SENT_STAGE

from .sale_order import SKIP

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    pmk_invoice_id = fields.Many2one(
        "sale.order", "Счёт покупателю", compute="_compute_pmk_invoice",
        help="Действующий счёт покупателю сделки (прежние редакции не в счёт).")
    pmk_invoice_count = fields.Integer("Счёт", compute="_compute_pmk_invoice")
    pmk_order_ids = fields.One2many("project.task", "pmk_deal_id", "Заказы в работе")
    pmk_order_count = fields.Integer("Заказ", compute="_compute_pmk_order_count")

    @api.depends("order_ids.state", "order_ids.pmk_is_revision")
    def _compute_pmk_invoice(self):
        Order = self.env["sale.order"]
        if not Order.has_access("read"):
            self.pmk_invoice_id = False
            self.pmk_invoice_count = 0
            return
        for lead in self:
            orders = lead._pmk_invoices()
            lead.pmk_invoice_id = orders[:1]
            lead.pmk_invoice_count = len(orders)

    @api.depends("pmk_order_ids")
    def _compute_pmk_order_count(self):
        Task = self.env["project.task"]
        if not Task.has_access("read"):
            self.pmk_order_count = 0
            return
        data = Task._read_group([("pmk_deal_id", "in", self.ids)], ["pmk_deal_id"], ["__count"])
        counts = {lead.id: count for lead, count in data}
        for lead in self:
            lead.pmk_order_count = counts.get(lead.id, 0)

    def _pmk_invoices(self):
        """Счета сделки без прежних редакций: сначала не отменённый, потом новее."""
        self.ensure_one()
        lead_id = self._origin.id
        if not lead_id:
            return self.env["sale.order"]
        orders = self.env["sale.order"].search([
            ("opportunity_id", "=", lead_id), ("pmk_is_revision", "=", False)])
        return orders.sorted(lambda order: (order.state != "cancel", order.id), reverse=True)

    def _pmk_current_invoice(self):
        self.ensure_one()
        return self.sudo()._pmk_invoices()[:1]

    # ─── Кнопки ─────────────────────────────────────────────────────────
    def action_open_invoice(self):
        """Кнопка «Счёт»: один — он сам, иначе список счетов сделки (пустой
        список объясняет, когда счёт появится)."""
        self.ensure_one()
        orders = self._pmk_invoices()
        action = self.env["ir.actions.act_window"]._for_xml_id("sale.action_orders")
        action.update(
            domain=[("opportunity_id", "=", self.id), ("pmk_is_revision", "=", False)],
            context={"default_opportunity_id": self.id,
                     "default_partner_id": self.partner_id.commercial_partner_id.id,
                     "create": False},
        )
        if len(orders) == 1:
            form = self.env.ref("sale.view_order_form").id
            action.update(res_id=orders.id, views=[(form, "form")], view_mode="form",
                          display_name=orders.display_name, name=orders.display_name)
        else:
            action["help"] = Markup("<p>%s</p><p>%s</p>") % (
                _("Счёта покупателю по сделке пока нет."),
                _("Он появится сам, когда сделку переведут в «КП отправлено»: изделия из "
                  "расчёта, цены клиенту."))
        return action

    def action_open_orders(self):
        """Кнопка «Заказ»: строки нет — форма новой с данными сделки, одна —
        она сама, несколько — список."""
        self.ensure_one()
        rows = self.env["project.task"].search([("pmk_deal_id", "=", self.id)])
        Task = self.env["project.task"]
        action = Task._pmk_rows_action(rows)
        if not rows:
            action["context"] = Task._pmk_row_defaults(deal=self, order=self._pmk_current_invoice())
        return action

    def _merge_get_fields_specific(self):
        """Объединение сделок: строки планировщика — к итоговой, как доборки."""
        fields_info = super()._merge_get_fields_specific()
        fields_info["pmk_order_ids"] = lambda fname, leads: [
            Command.link(row.id) for row in leads.pmk_order_ids]
        return fields_info

    # ─── Где ловим ──────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        if not self.env.context.get(SKIP):
            leads._pmk_orders_react(stage=True, lost=False)
        return leads

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get(SKIP):
            return res
        stage = "stage_id" in vals
        lost = bool({"active", "probability"} & set(vals))
        if stage or lost:
            self._pmk_orders_react(stage=stage, lost=lost)
        return res

    def _pmk_orders_react(self, stage, lost):
        kp_stage = self.env.ref(KP_SENT_STAGE, raise_if_not_found=False)
        for lead in self:
            if lead.type != "opportunity":
                continue
            if lost and lead.won_status == "lost":
                lead._pmk_orders_safely("_pmk_order_lost")
            elif stage and lead.active:
                if lead.stage_id.is_won:
                    lead._pmk_orders_safely("_pmk_order_won")
                elif kp_stage and lead.stage_id == kp_stage and lead.won_status == "pending":
                    lead._pmk_orders_safely("_pmk_issue_invoice")

    def _pmk_orders_safely(self, method, *args):
        """Сбой счёта или планировщика не роняет сохранение сделки."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                return getattr(self, method)(*args)
        except Exception as error:  # noqa: BLE001 — сигнал, а не запрет
            _logger.exception("pmk_orders: %s по сделке %s не вышел", method, self.id)
            self._pmk_orders_note(_(
                "Счёт покупателю / заказ в работе: не получилось (%(error)s). Стадия сделки "
                "сменилась как обычно; скажите администратору.", error=str(error)))
        return False

    def _pmk_orders_note(self, text):
        """Заметка в ленту сделки — от того, кто менял сделку."""
        self.ensure_one()
        body = text if isinstance(text, Markup) else escape(text)
        self.sudo()._message_log(body=body)

    # ─── «КП отправлено» → счёт ─────────────────────────────────────────
    def _pmk_issue_invoice(self, spec=None):
        """Выставить (или обновить редакцией) счёт покупателю из расчёта.

        Вернёт действующий счёт или пустой набор. Ничего не запрещает: чего
        не хватило — пишет в ленту сделки.
        """
        self.ensure_one()
        lead = self.with_context(**{SKIP: True})
        Order = self.env["sale.order"].sudo()
        spec = (spec or lead._pmk_invoice_source_spec()).sudo()
        if not spec:
            lead._pmk_orders_note(_("Счёт покупателю не выставлен: у сделки нет расчёта."))
            return Order
        priced = Order._pmk_priced_products(spec)
        if not priced:
            lead._pmk_orders_note(_(
                "Счёт покупателю не выставлен: в расчёте %s нет цены клиенту ни у одного "
                "изделия.", spec.name))
            return Order
        partner = (lead.partner_id or spec.partner_id).commercial_partner_id
        if not partner:
            lead._pmk_orders_note(_(
                "Счёт покупателю не выставлен: не указан клиент — ни в сделке, ни в "
                "расчёте %s.", spec.name))
            return Order
        org = spec.pmk_org_id or lead.pmk_org_id
        wanted = Order._pmk_spec_signature(spec, partner, org)
        invoice = lead._pmk_current_invoice()
        skipped = spec.product_ids - priced
        if not invoice:
            invoice = Order._pmk_create_from_spec(lead, spec, partner, org)
            text = _("Счёт покупателю %(invoice)s выставлен из расчёта %(spec)s: изделий "
                     "%(count)s, сумма %(total)s (в т. ч. налог %(tax)s). Ждём оплату.")
        elif invoice.state == "sale":
            if invoice._pmk_signature() != wanted:
                lead._pmk_orders_note(_(
                    "Счёт %(invoice)s уже в работе (оплачен) — расчёт %(spec)s с тех пор "
                    "изменился, счёт не меняли.",
                    invoice=invoice.display_name, spec=spec.name))
            return invoice
        elif invoice._pmk_signature() == wanted:
            if invoice.state == "sent":
                return invoice
            invoice._pmk_mark_sent()
            text = _("Счёт покупателю %(invoice)s снова выставлен (расчёт %(spec)s не "
                     "менялся): сумма %(total)s. Ждём оплату.")
        else:
            invoice._pmk_new_revision(spec, partner, org)
            text = _("Счёт покупателю %(invoice)s: расчёт %(spec)s изменился — новая "
                     "редакция, прежняя сохранена только для чтения. Сумма %(total)s "
                     "(в т. ч. налог %(tax)s). Ждём оплату.")
        params = {
            "invoice": invoice.display_name,
            "spec": spec.name,
            "count": len(priced),
            "total": self._pmk_money(invoice.amount_total, invoice.currency_id),
            "tax": self._pmk_money(invoice.amount_tax, invoice.currency_id),
        }
        text = text % params
        if skipped:
            text += " " + _("Без цены клиенту, в счёт не попали: %s.",
                            ", ".join(skipped.mapped("name")))
        lead._pmk_orders_note(text)
        return invoice

    def _pmk_invoice_source_spec(self):
        """Расчёт для счёта, когда его не назвали (перетаскивание, «Выиграно»).

        Счёт уже выставлен — из того же расчёта, по которому выставлен (он ещё
        этой сделки): редакция появится, только если поменялся ОН. Счёта нет
        или его расчёт удалён / ушёл к другой сделке — главный расчёт сделки.
        """
        self.ensure_one()
        spec = self._pmk_current_invoice().pmk_spec_id.sudo()
        if spec.exists() and spec.opportunity_id.id == self._origin.id:
            return spec
        return self.pmk_spec_id

    @api.model
    def _pmk_money(self, amount, currency):
        """«9 500 000,00 ₽» — неразрывные пробелы, как в карточках сделки."""
        lang = self.env["res.lang"]._lang_get(self.env.lang or "ru_RU") or self.env["res.lang"]._lang_get("ru_RU")
        if lang:
            text = lang.format("%.2f", amount, grouping=True)
        else:
            text = "%.2f" % amount
        symbol = currency.symbol or ""
        return ("%s %s" % (text, symbol)).strip().replace(" ", " ")

    # ─── «Выиграно» → подтверждение и строка планировщика ───────────────
    def _pmk_order_won(self):
        self.ensure_one()
        lead = self.with_context(**{SKIP: True})
        invoice = lead._pmk_current_invoice()
        if not invoice or invoice.state == "cancel":
            invoice = lead._pmk_issue_invoice() or invoice
        Task = self.env["project.task"]
        if invoice and invoice.state in ("draft", "sent"):
            # Без send_email: подтверждение письма клиенту не шлёт.
            invoice.sudo().with_context(**{SKIP: True}).action_confirm()
        if invoice and invoice.state == "sale":
            invoice.sudo()._pmk_ensure_planner_row()
            return True
        rows = Task.sudo().with_context(active_test=False).search([("pmk_deal_id", "=", lead.id)], limit=1)
        if not rows:
            Task._pmk_create_order_row(deal=lead)
            lead._pmk_orders_note(_(
                "Заказ в работе появился без счёта покупателю: счёт выставить не вышло "
                "(см. заметку выше). Сумму строки — руками."))
        return True

    # ─── «Проиграно» → счёт отменён ─────────────────────────────────────
    def _pmk_order_lost(self):
        self.ensure_one()
        invoice = self._pmk_current_invoice()
        if not invoice or invoice.state == "cancel":
            return False
        invoice = invoice.with_context(**{SKIP: True}, mail_auto_subscribe_no_notify=True)
        if invoice.locked:
            invoice.action_unlock()
        invoice._action_cancel()
        self._pmk_orders_note(_(
            "Сделка проиграна — счёт покупателю %s отменён. Строка «Заказов в работе», "
            "если была, осталась.", invoice.display_name))
        return True
