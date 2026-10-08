# -*- coding: utf-8 -*-
"""Окно «Отправить КП»: что станет со счётом (шаг З-9, 09.10.2026).

Согласование — наблюдение, а не запрет: отправить КП можно и с
несогласованным счётом, но в окне это видно жёлтой плашкой («Счёт СЧ-… не
согласован»). Остальное — серой строкой-справкой: счёта нет и он заведётся
при отправке, черновик собран из другого расчёта и перейдёт на этот, счёт
уже отправлен и будет новая редакция, счёт в работе и не изменится,
отменённый снова станет «Отправлен». Отдельной жёлтой плашкой — услуги и
условия счёта: в КП (печать расчёта) они не входят до шаблона шага 62.

Только в окне КП (флаг pmk_kp_send и расчёт — pmk_bridge _pmk_kp_spec); у
расчёта без сделки — пусто. Счёт читается через sudo: окно открывает и
технолог без прав на счета, а показываем только номер и состояние.
"""
from odoo import _, api, fields, models
from odoo.tools import is_html_empty

from odoo.addons.pmk_bridge.models.kp_send import KP_SEND_FLAG

from .sale_order import money_text


class MailComposeMessageInvoice(models.TransientModel):
    _inherit = "mail.compose.message"

    pmk_kp_invoice_text = fields.Char(compute="_compute_pmk_kp_invoice")
    pmk_kp_invoice_hint = fields.Char(compute="_compute_pmk_kp_invoice")
    pmk_kp_invoice_extra = fields.Char(compute="_compute_pmk_kp_invoice")

    @api.depends("model", "res_ids", "composition_mode")
    @api.depends_context(KP_SEND_FLAG)
    def _compute_pmk_kp_invoice(self):
        for composer in self:
            composer.pmk_kp_invoice_text = False
            composer.pmk_kp_invoice_hint = False
            composer.pmk_kp_invoice_extra = False
            spec = composer._pmk_kp_spec().sudo()
            deal = spec.opportunity_id
            if not spec or not deal or getattr(spec, "pmk_kind", "kp") == "tech":
                continue
            invoice = deal._pmk_current_invoice()
            Order = self.env["sale.order"].sudo()
            if not invoice:
                composer.pmk_kp_invoice_text = _(
                    "Счёта покупателю ещё нет: после отправки клиенту он заведётся из этого "
                    "расчёта и станет «Отправлен».")
                continue
            if invoice.state == "sale":
                composer.pmk_kp_invoice_text = _(
                    "Счёт %s в работе (оплачен) — отправка КП его не изменит.",
                    invoice.display_name)
                continue
            composer.pmk_kp_invoice_extra = composer._pmk_kp_extra_text(invoice)
            partner = Order._pmk_invoice_partner(deal, spec)
            org = spec.pmk_org_id or deal.pmk_org_id
            changed = (invoice.pmk_spec_id != spec or invoice._pmk_signature()
                       != Order._pmk_spec_signature(spec, partner, org))
            if invoice.state == "draft":
                text = _("После отправки счёт %s станет «Отправлен».", invoice.display_name)
                if invoice.pmk_spec_id and invoice.pmk_spec_id != spec:
                    text += " " + _("Черновик собран из расчёта %s — перейдёт на этот.",
                                    invoice.pmk_spec_id.name)
                composer.pmk_kp_invoice_text = text
                if invoice.pmk_approval == "approved" and changed:
                    # Пересборка из этого расчёта сбросит согласование
                    # (sale_order._pmk_sync_from_spec) — счёт уйдёт без него.
                    composer.pmk_kp_invoice_hint = _(
                        "Счёт %(invoice)s согласован по расчёту %(old)s — изделия обновятся из "
                        "этого расчёта, согласование сбросится: отправить можно, на счёте "
                        "останется пометка «без согласования».", invoice=invoice.display_name,
                        old=invoice.pmk_spec_id.name or _("(нет)"))
                elif invoice.pmk_approval != "approved":
                    composer.pmk_kp_invoice_hint = _(
                        "Счёт %(invoice)s не согласован%(pending)s — отправить можно, на счёте "
                        "останется пометка.", invoice=invoice.display_name,
                        pending=_(" (ждёт руководителя)") if invoice.pmk_approval == "pending"
                        else "")
            elif invoice.state == "cancel":
                # crm_lead._pmk_invoice_kp_sent: отменённый снова «Отправлен»;
                # расчёт менялся — новой редакцией.
                if changed:
                    composer.pmk_kp_invoice_hint = _(
                        "Счёт %(invoice)s отменён — после отправки снова «Отправлен» новой "
                        "редакцией: ред. %(next)s (прежняя сохранится).",
                        invoice=invoice.display_name, next=(invoice.pmk_revision or 1) + 1)
                else:
                    composer.pmk_kp_invoice_text = _(
                        "Счёт %s отменён — после отправки снова «Отправлен».",
                        invoice.display_name)
            elif changed:
                composer.pmk_kp_invoice_hint = _(
                    "Счёт %(invoice)s уже отправлен, расчёт изменился — после отправки будет "
                    "ред. %(next)s (прежняя сохранится).", invoice=invoice.display_name,
                    next=(invoice.pmk_revision or 1) + 1)
            else:
                composer.pmk_kp_invoice_text = _(
                    "Счёт %s уже отправлен и с расчётом совпадает — не изменится.",
                    invoice.display_name)

    def _pmk_kp_extra_text(self, invoice):
        """Что есть в счёте, но не в КП (печать расчёта, pmk_bridge): услуги
        (строки не из расчёта) и условия. До шаблона КП/счёта (шаг 62) клиент
        их в PDF не увидит — жёлтой плашкой, ничего не запрещая."""
        services = invoice.order_line.filtered(
            lambda line: not line.pmk_from_spec and not line.display_type)
        terms = []
        if invoice.payment_term_id or invoice.pmk_payment_note:
            terms.append(_("оплата"))
        if invoice.pmk_lead_days > 0:
            terms.append(_("срок изготовления"))
        if invoice.pmk_delivery:
            terms.append(_("доставка"))
        if not is_html_empty(invoice.note):
            terms.append(_("прочие условия"))
        if not services and not terms:
            return False
        parts = []
        if services:
            def money(amount):
                return money_text(self.env, amount, invoice.currency_id)

            def title(line):
                name = (line.name or "").strip()
                return name.splitlines()[0] if name else _("Услуга")

            listed = "; ".join("%s — %s" % (title(line), money(line.price_total))
                               for line in services[:3])
            if len(services) > 3:
                listed += _(" и ещё %s", len(services) - 3)
            parts.append(_("услуги счёта (%(list)s; счёт больше КП на %(sum)s)",
                           list=listed, sum=money(sum(services.mapped("price_total")))))
        if terms:
            parts.append(_("условия: %s", ", ".join(terms)))
        return _("В КП не войдут %s — впишите их в письмо.", " и ".join(parts))
