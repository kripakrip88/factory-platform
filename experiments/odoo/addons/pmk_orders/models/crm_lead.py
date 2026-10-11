# -*- coding: utf-8 -*-
"""Сделка ↔ счёт покупателю ↔ строка планировщика (шаги З-2 и З-9).

РЕШЕНИЯ АНТОНА 09.10.2026 (шаг З-9, меняют схему З-2): «сначала отправили, а
потом перетащили сделку. Автоотправки не нужны, перенос либо руками, либо
после нажатия на кнопку «Отправить КП»». Счёт сам больше НЕ заводится:
черновик — кнопкой «Счёт» в расчёте (metal_spec.py).

  «Отправить КП» в расчёте (письмо ушло людям клиента, pmk_deal kp_sent.py)
      — счёт этого расчёта становится «Отправлен»: черновик (переключённый на
      отправленный расчёт, если был из другого); нет черновика — заводится из
      расчёта и сразу «Отправлен» (КП реально ушло). Счёт уже отправлен и
      расчёт с тех пор поменялся — новая РЕДАКЦИЯ того же счёта (снимок
      прежней). Сделка переходит в «КП отправлено», как и раньше (pmk_deal).
  Сделку перенесли в «КП отправлено» руками — КП ушло вне системы: черновик
      помечается «Отправлен» с заметкой; счёта нет — только заметка в ленте
      сделки (счёт НЕ заводится); отправленный — не меняется (расчёт
      изменился — заметка «ред. N — по «Отправить КП»»).
  «Выиграно» = пришла предоплата или гарантийное письмо — счёт
      подтверждается (складских документов нет: товар-услуга) и появляется
      РОВНО ОДНА строка «Заказов в работе» в «Очереди». Счёта нет — строка
      без счёта и заметка (счёт не заводится).
  «Проиграно» — действующий счёт отменяется. Строка планировщика, если была,
      остаётся.

СИГНАЛ, А НЕ ЗАПРЕТ. Нет расчёта, цены или клиента — стадия меняется как
обычно, в ленте сделки — заметка, почему. Изделия без цены в счёт не идут
(как и в печать КП) и перечислены в заметке. Сбой нашего кода не роняет
сохранение сделки: откат до точки сохранения, заметка в ленте, ошибка в
журнал. Писем клиенту здесь нет ни одного: письмо уходит только по
«Отправить» в окне «Отправить КП».

ГДЕ ЛОВИМ. write() сделки после штатного: сюда приходят кнопки «Выиграно» и
«Проиграно» (action_set_won / action_set_lost), перетаскивание в канбане,
правка в списке. Переход по отправке КП (pmk_deal, _pmk_kp_move_stage) идёт
с контекстом pmk_orders_skip, счёт там — явно (kp_sent.py). Создание сделки
сразу в «КП отправлено» (бот, импорт) счёт не трогает.
"""
import logging

from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models

from odoo.addons.pmk_deal.models.kp_sent import KP_SENT_STAGE

from .project_task import NO_REPLAN
from .sale_order import ACT_APPROVE, ACT_REWORK, SKIP, money_text, ru_env

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
                _("Черновик заводится кнопкой «Счёт» в расчёте: изделия из расчёта, цены "
                  "клиенту. Отправленным он станет по «Отправить КП»."))
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

    def action_pmk_won(self):
        """Кнопка «Выиграно» на форме сделки (шаг З-15): короткое окно «Оплата /
        гарантия» — сумма и дата оплаты, гарантийное письмо. Окно необязательное
        («Пропустить»), ничего не запрещает; крестик — сделка остаётся в
        работе. Сделка не в работе (уже выиграна, проиграна, в архиве, лид) —
        как штатная кнопка, без окна. Перетаскивание в воронке, строка стадий,
        «Оплата пришла — в работу» и ссылка из письма идут мимо окна — по
        штатному пути (write стадии)."""
        self.ensure_one()
        if self.type != "opportunity" or not self.active or self.won_status != "pending":
            return self.action_set_won_rainbowman()
        view = self.env.ref("pmk_orders.view_pmk_orders_won_wizard_form", raise_if_not_found=False)
        return {
            "type": "ir.actions.act_window",
            "name": _("Оплата / гарантия"),
            "res_model": "pmk.orders.won.wizard",
            "view_mode": "form",
            "views": [(view.id if view else False, "form")],
            "target": "new",
            "context": {"default_lead_id": self.id},
        }

    def _pmk_won_payment(self, amount, day, guarantee):
        """Окно «Оплата / гарантия» → строка «Заказов в работе» и заметки.

        Пишем в ОДНУ строку (_pmk_won_row): у сделки их может быть больше
        (объединение сделок, архивная) — чужая оплата и удвоенная сумма
        «Оплачено» в списке ни к чему. Сумма и дата — в «Сумму оплаты» и
        «Дату оплаты» строки; дата впервые — сдача от неё. Гарантийное
        письмо — галочка строки, старт и сдача — от дня письма. В ленту
        строки — всегда итоговая заметка «откуда сдача» (даже если даты не
        поменялись), в ленту сделки и счёта — что внесли. Писем нет. Пишем
        от sudo: продавцу без «Проектов» строка всё равно своя (правило
        записей), автор в ленте — он сам.
        """
        self.ensure_one()
        invoice = self._pmk_current_invoice()
        row = self._pmk_won_row(invoice)
        currency = (invoice.currency_id or self.company_id.currency_id
                    or self.env.company.currency_id)
        parts = []
        if guarantee:
            parts.append(_("гарантийное письмо от %s (вместо оплаты)", day.strftime("%d.%m.%Y")))
        if amount > 0:
            money = self._pmk_money(amount, currency)
            base = invoice.amount_total if invoice else self.expected_revenue
            if base:
                money = _("%(money)s (%(pct)s %% от %(of)s)", money=money,
                          pct=round(amount / base * 100.0),
                          of=_("счёта") if invoice else _("суммы сделки"))
            parts.append(_("оплата %(money)s от %(day)s", money=money,
                           day=day.strftime("%d.%m.%Y")))
        if not parts:
            return row
        vals = {}
        if amount > 0:
            vals.update(pmk_paid_amount=amount, pmk_paid_date=day)
        if guarantee:
            vals["pmk_guarantee"] = True
        if row:
            first_paid = amount > 0 and not row.pmk_paid_date
            row.with_context(**{NO_REPLAN: True}).write(vals)
            if guarantee:
                row._pmk_replan_from_guarantee(day, always_note=True)
            elif first_paid:
                row._pmk_replan_from_payment(always_note=True)
        text = _("Выиграно: %s.", "; ".join(parts))
        if not row:
            text += " " + _("Строки «Заказов в работе» нет — внесите в неё руками, когда появится.")
        elif self.env["project.task"].sudo().with_context(active_test=False).search_count(
                [("pmk_deal_id", "=", self.id)]) > 1:
            text += " " + _("Записано в строку «%s» (у сделки их несколько).", row.name)
        self._pmk_orders_note(text)
        if invoice:
            invoice._pmk_note(text)
        return row

    def _pmk_won_row(self, invoice):
        """Строка для оплаты из окна: действующая со счётом сделки → любая
        действующая → со счётом в архиве → первая."""
        self.ensure_one()
        rows = self.env["project.task"].sudo().with_context(active_test=False).search(
            [("pmk_deal_id", "=", self.id)], order="id")
        if invoice:
            rows = rows.sorted(lambda row: (not row.active, row.pmk_sale_order_id != invoice, row.id))
        else:
            rows = rows.sorted(lambda row: (not row.active, row.id))
        return rows[:1]

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
            leads._pmk_orders_react(stage=True, lost=False, created=True)
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

    def _pmk_orders_react(self, stage, lost, created=False):
        kp_stage = self.env.ref(KP_SENT_STAGE, raise_if_not_found=False)
        for lead in self:
            if lead.type != "opportunity":
                continue
            if lost and lead.won_status == "lost":
                lead._pmk_orders_safely("_pmk_order_lost")
            elif stage and lead.active:
                if lead.stage_id.is_won:
                    lead._pmk_orders_safely("_pmk_order_won")
                elif (not created and kp_stage and lead.stage_id == kp_stage
                        and lead.won_status == "pending"):
                    lead._pmk_orders_safely("_pmk_invoice_sent_by_hand")

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

    # ─── «Отправить КП» → счёт этого расчёта «Отправлен» ────────────────
    def _pmk_invoice_kp_sent(self, spec):
        """КП расчёта ``spec`` ушло клиенту (pmk_deal, kp_sent.py): счёт этого
        расчёта — «Отправлен». Вернёт действующий счёт или пустой набор.

        Ничего не запрещает: чего не хватило — пишет в ленту сделки. Все
        заметки начинаются со «Счёт» — тесты отправки КП (pmk_deal) их так
        отличают от заметки «КП … отправлено».
        """
        self.ensure_one()
        lead = self.with_context(**{SKIP: True})
        Order = self.env["sale.order"].sudo()
        spec = spec.sudo()
        priced = Order._pmk_priced_products(spec)
        if not priced:
            lead._pmk_orders_note(_(
                "Счёт покупателю не отмечен отправленным: в расчёте %s нет цены клиенту ни "
                "у одного изделия.", spec.name))
            return Order.browse()
        partner = Order._pmk_invoice_partner(lead, spec)
        if not partner:
            lead._pmk_orders_note(_(
                "Счёт покупателю не отмечен отправленным: не указан клиент — ни в сделке, "
                "ни в расчёте %s.", spec.name))
            return Order.browse()
        org = spec.pmk_org_id or lead.pmk_org_id
        wanted = Order._pmk_spec_signature(spec, partner, org)
        invoice = lead._pmk_current_invoice()
        skipped = spec.product_ids - priced
        if not invoice:
            invoice = Order._pmk_create_from_spec(lead, spec, partner, org)
            invoice._pmk_mark_sent(_("КП %s отправлено — счёт заведён из расчёта и отмечен "
                                     "«Отправлен».", spec.name))
            text = _("Счёт покупателю %(invoice)s: КП %(spec)s отправлено — счёт заведён из "
                     "расчёта и отмечен «Отправлен» (черновика не было, согласования не было): "
                     "изделий %(count)s, сумма %(total)s (%(tax)s). Ждём оплату.")
        elif invoice.state == "draft":
            old = invoice.pmk_spec_id
            invoice._pmk_sync_from_spec(spec)
            approved = invoice.pmk_approval == "approved"
            invoice._pmk_mark_sent(_("Отправлен вместе с КП %s.", spec.name))
            text = _("Счёт покупателю %(invoice)s отправлен вместе с КП %(spec)s: сумма "
                     "%(total)s (%(tax)s). Ждём оплату.")
            if old and old != spec:
                text += " " + _("Черновик был из расчёта %s — переключён на отправленный.",
                                old.name)
            if not approved:
                text += " " + _("Счёт не согласован.")
        elif invoice.state == "sale":
            if invoice._pmk_signature() != wanted:
                lead._pmk_orders_note(_(
                    "Счёт %(invoice)s уже в работе (оплачен) — расчёт %(spec)s с тех пор "
                    "изменился, счёт не меняли.",
                    invoice=invoice.display_name, spec=spec.name))
            return invoice
        elif invoice._pmk_signature() == wanted and invoice.pmk_spec_id == spec:
            if invoice.state == "sent":
                return invoice
            invoice._pmk_mark_sent()
            text = _("Счёт покупателю %(invoice)s снова «Отправлен» (расчёт %(spec)s не "
                     "менялся): сумма %(total)s. Ждём оплату.")
        else:
            invoice._pmk_new_revision(spec, partner, org)
            text = _("Счёт покупателю %(invoice)s: расчёт %(spec)s изменился — новая "
                     "редакция отправлена, прежняя сохранена только для чтения. Сумма "
                     "%(total)s (%(tax)s). Ждём оплату.")
        text = text % lead._pmk_invoice_params(invoice, spec, priced)
        if skipped:
            text += " " + _("Без цены клиенту, в счёт не попали: %s.",
                            ", ".join(skipped.mapped("name")))
        lead._pmk_orders_note(text)
        return invoice

    def _pmk_invoice_params(self, invoice, spec, priced):
        tax_label, tax_amount = invoice._pmk_tax_line()
        tax = tax_label if tax_amount is None else "%s %s" % (
            tax_label, self._pmk_money(tax_amount, invoice.currency_id))
        return {
            "invoice": invoice.display_name,
            "spec": spec.name,
            "count": len(priced),
            "total": self._pmk_money(invoice.amount_total, invoice.currency_id),
            "tax": tax,
        }

    # ─── Сделку перенесли в «КП отправлено» руками ──────────────────────
    def _pmk_invoice_sent_by_hand(self):
        """КП ушло вне системы (почтой с телефона, мессенджером): черновик —
        «Отправлен», счёта нет — заметка (счёт НЕ заводится)."""
        self.ensure_one()
        lead = self.with_context(**{SKIP: True})
        invoice = lead._pmk_current_invoice()
        if not invoice:
            lead._pmk_orders_note(_(
                "Сделку перенесли в «КП отправлено», а счёта покупателю у неё нет — сам он "
                "не заводится. Черновик — кнопкой «Счёт» в расчёте; отправленным он станет "
                "по «Отправить КП» или при таком же переносе."))
            return invoice
        if invoice.state == "draft":
            approved = invoice.pmk_approval == "approved"
            invoice._pmk_mark_sent(_(
                "Отмечен «Отправлен»: сделку перенесли в «КП отправлено» руками (КП ушло "
                "вне системы)."))
            text = _("Счёт покупателю %s отмечен «Отправлен»: сделку перенесли в «КП "
                     "отправлено» руками.", invoice.display_name)
            if not approved:
                text += " " + _("Счёт не согласован.")
            lead._pmk_orders_note(text)
            return invoice
        spec = lead._pmk_invoice_source_spec().sudo()
        Order = self.env["sale.order"].sudo()
        partner = Order._pmk_invoice_partner(lead, spec) if spec else invoice.partner_id
        org = (spec.pmk_org_id or lead.pmk_org_id) if spec else invoice.pmk_org_id
        changed = bool(spec) and invoice._pmk_signature() != Order._pmk_spec_signature(
            spec, partner, org)
        if invoice.state == "sent":
            if changed:
                lead._pmk_orders_note(_(
                    "Счёт покупателю %(invoice)s уже отправлен; расчёт %(spec)s с тех пор "
                    "изменился — ред. %(next)s появится по «Отправить КП» в расчёте.",
                    invoice=invoice.display_name, spec=spec.name,
                    next=(invoice.pmk_revision or 1) + 1))
            return invoice
        if invoice.state == "sale":
            if changed:
                lead._pmk_orders_note(_(
                    "Счёт %(invoice)s уже в работе (оплачен) — расчёт %(spec)s с тех пор "
                    "изменился, счёт не меняли.", invoice=invoice.display_name,
                    spec=spec.name))
            return invoice
        # Отменённый (сделку восстановили после «Проиграно» и снова перенесли).
        return lead._pmk_invoice_reopen(invoice, spec, partner, org, changed)

    def _pmk_invoice_reopen(self, invoice, spec, partner, org, changed):
        """Отменённый счёт снова «Отправлен»: расчёт не менялся — тот же; менялся
        и есть цены — новая редакция (прежняя хранится)."""
        self.ensure_one()
        if changed and spec and self.env["sale.order"]._pmk_priced_products(spec) and partner:
            invoice._pmk_new_revision(spec, partner, org)
            self._pmk_orders_note(_(
                "Счёт покупателю %(invoice)s снова «Отправлен»: расчёт %(spec)s изменился — "
                "новая редакция, прежняя сохранена только для чтения.",
                invoice=invoice.display_name, spec=spec.name))
        else:
            invoice._pmk_mark_sent()
            self._pmk_orders_note(_(
                "Счёт покупателю %s снова «Отправлен».", invoice.display_name))
        return invoice

    def _pmk_invoice_source_spec(self):
        """Расчёт счёта, когда его не назвали (перенос руками, «Выиграно»).

        Счёт уже есть — тот, по которому он собран (он ещё этой сделки):
        новый вариант расчёта, ставший главным, счёт сам не переписывает. Его
        расчёт удалён или ушёл к другой сделке — главный расчёт сделки.
        """
        self.ensure_one()
        spec = self._pmk_current_invoice().pmk_spec_id.sudo()
        if spec.exists() and spec.opportunity_id.id == self._origin.id:
            return spec
        return self.pmk_spec_id

    @api.model
    def _pmk_money(self, amount, currency):
        """«9 500 000,00 ₽» — неразрывные пробелы, как в карточках сделки."""
        return money_text(self.env, amount, currency)

    # ─── «Выиграно» → подтверждение и строка планировщика ───────────────
    def _pmk_order_won(self):
        self.ensure_one()
        lead = self.with_context(**{SKIP: True})
        invoice = lead._pmk_current_invoice()
        Task = self.env["project.task"]
        if invoice and invoice.state == "cancel":
            spec = lead._pmk_invoice_source_spec().sudo()
            Order = self.env["sale.order"].sudo()
            partner = Order._pmk_invoice_partner(lead, spec) if spec else invoice.partner_id
            org = (spec.pmk_org_id or lead.pmk_org_id) if spec else invoice.pmk_org_id
            changed = bool(spec) and invoice._pmk_signature() != Order._pmk_spec_signature(
                spec, partner, org)
            lead._pmk_invoice_reopen(invoice, spec, partner, org, changed)
        if invoice and invoice.state == "draft":
            lead._pmk_orders_note(_(
                "Счёт покупателю %s в работу из черновика: отправленным он не отмечался.",
                invoice.display_name))
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
                "Заказ в работе появился без счёта покупателю: счёта у сделки нет (черновик — "
                "кнопкой «Счёт» в расчёте). Сумму строки — руками."))
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
        ru_env(invoice)._action_cancel()
        invoice.activity_unlink([ACT_APPROVE, ACT_REWORK])
        self._pmk_orders_note(_(
            "Сделка проиграна — счёт покупателю %s отменён. Строка «Заказов в работе», "
            "если была, осталась.", invoice.display_name))
        return True
