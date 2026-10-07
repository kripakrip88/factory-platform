# -*- coding: utf-8 -*-
"""Счёт покупателю из расчёта и его редакции (разбор UX, шаг З-2, 08.10.2026).

«Счёт покупателю» — штатный заказ клиента (sale.order), по-заводски (меню и
слова — pmk_theme). Для завода КП и счёт — один документ: когда сделка
переходит в «КП отправлено», из её расчёта выставляется счёт (crm_lead.py,
_pmk_issue_invoice). Здесь — то, что живёт на самом счёте:

СТРОКИ — изделия расчёта по отдельности: служебный товар-услуга
«Изготовление металлоконструкций» (data/product.xml: без склада и отгрузок),
описание = название изделия, количество, «шт», цена = цена клиенту за штуку.
Строка помнит своё изделие (pmk_spec_product_id). Налог — режим организации
на дату счёта (pmk_org); компания — «цены включают налог» (решение Антона
08.10.2026): цены расчёта окончательные, налог выделяется из них, сумма
счёта = сумме КП. Цена строки от налога не зависит (ядро пересчитывает её
под другой налог только через налоговую позицию — её для режимов нет).

РЕДАКЦИИ (решение Антона 08.10.2026). Расчёт поменяли после отправки и
снова отправили КП — не новый счёт, а новая редакция того же: номер тот же,
«ред. 2», «ред. 3». Действующий счёт остаётся той же записью (тот же номер,
ссылки из сделки, планировщика и ленты живы), счётчик pmk_revision растёт.
Прежняя редакция — СНИМОК: отдельный sale.order с тем же номером, собранный
явными значениями (price_unit и tax_ids — вычисляемые поля, copy() их не
переносит), отменён, заблокирован, без сделки (не попадает в счётчики
sale_crm и на схему «Связи»), со ссылкой на действующий. Снимок только для
чтения: правка содержания, смена состояния и удаление — ошибкой
(«для анализа: что и по какой цене уходило клиенту»). Свои операции идут
суперпользователем (sudo) с контекстом pmk_revision_freeze: флаг без sudo не
действует — контекст RPC-запроса задаёт браузер, и одним флагом снимок
правился бы из клиента.

«ПОДТВЕРДИТЬ» = «ВЫИГРАНО». Кнопка подписана «Оплата пришла — в работу»:
подтверждение счёта переводит сделку в «Выиграно» (там появляется строка
планировщика). Нет сделки — строка планировщика появляется сразу. Писем не
шлём: action_confirm без send_email.
"""
import logging

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import clean_context

_logger = logging.getLogger(__name__)

# Контекст: свои операции со снимками (создание, отмена, блокировка).
FREEZE = "pmk_revision_freeze"
# Контекст: не запускать связку сделка ↔ счёт ↔ планировщик (crm_lead.py).
SKIP = "pmk_orders_skip"

# Поля снимка, которые меняют содержание того, что ушло клиенту (и что
# печатается: ссылка клиента, дата поставки, инкотермс sale_stock — их
# имена держим и без модуля, лишнее имя ничего не ломает). Лента, вложения, ссылка
# портала, активности не здесь: открытие и печать снимка пишут их сами.
# Менеджер, команда, теги в форме снимка закрыты видом (readonly), сервер
# их не держит: это не содержание счёта.
SNAPSHOT_LOCKED_FIELDS = frozenset({
    "name", "order_line", "partner_id", "partner_invoice_id", "partner_shipping_id",
    "pmk_org_id", "state", "date_order", "validity_date", "pricelist_id",
    "fiscal_position_id", "note", "payment_term_id", "client_order_ref",
    "commitment_date", "incoterm", "incoterm_location",
    "pmk_spec_id", "opportunity_id",
    "pmk_revision", "pmk_is_revision", "pmk_revision_of_id", "locked", "company_id",
    "currency_id",
})


def freeze_allowed(env):
    """Свои операции со снимком: sudo И флаг вместе (флаг один — от клиента)."""
    return bool(env.su and env.context.get(FREEZE))


def snapshot_error(order):
    return UserError(_(
        "%(name)s — прежняя редакция счёта, только для чтения: по ней видно, что и по "
        "какой цене уходило клиенту. Действующая редакция — %(current)s.",
        name=order.display_name,
        current=order.pmk_revision_of_id.display_name or _("не найдена")))


class SaleOrder(models.Model):
    _inherit = "sale.order"

    pmk_spec_id = fields.Many2one(
        "pmk.metal.spec", "Расчёт", index=True, ondelete="set null", copy=False,
        tracking=True,
        help="Расчёт, из которого выставлен счёт: его изделия — строки счёта.")
    pmk_revision = fields.Integer(
        "Редакция", default=1, copy=False, readonly=True,
        help="Номер редакции: расчёт поменяли после отправки и снова отправили КП — "
             "редакция растёт, номер счёта тот же.")
    pmk_is_revision = fields.Boolean(
        "Прежняя редакция", index=True, copy=False, readonly=True,
        help="Снимок того, что уходило клиенту до следующей редакции. Только для чтения.")
    pmk_revision_of_id = fields.Many2one(
        "sale.order", "Действующая редакция", index=True, ondelete="set null",
        copy=False, readonly=True)
    pmk_revision_ids = fields.One2many(
        "sale.order", "pmk_revision_of_id", "Прежние редакции", readonly=True)
    pmk_revision_label = fields.Char("Ред.", compute="_compute_pmk_revision_label")
    pmk_deal_number = fields.Char(
        related="opportunity_id.pmk_number", string="Номер сделки")
    pmk_task_ids = fields.One2many("project.task", "pmk_sale_order_id", "Заказы в работе")
    pmk_task_count = fields.Integer("Заказ", compute="_compute_pmk_task_count")

    @api.depends("pmk_revision", "pmk_is_revision")
    def _compute_pmk_revision_label(self):
        for order in self:
            revision = order.pmk_revision or 1
            order.pmk_revision_label = (
                "ред. %s" % revision if order.pmk_is_revision or revision > 1 else False)

    @api.depends("pmk_revision", "pmk_is_revision")
    def _compute_display_name(self):
        """«СЧ-00001 ред. 2» — номер целиком, редакция сразу за ним (и перед
        клиентом, если ядро его дописывает: sale_show_partner_name)."""
        super()._compute_display_name()
        for order in self:
            label, name, shown = order.pmk_revision_label, order.name, order.display_name
            if label and name and shown and shown.startswith(name):
                order.display_name = "%s %s%s" % (name, label, shown[len(name):])

    @api.depends("pmk_task_ids")
    def _compute_pmk_task_count(self):
        Task = self.env["project.task"]
        if not Task.has_access("read"):
            self.pmk_task_count = 0
            return
        data = Task._read_group(
            [("pmk_sale_order_id", "in", self.ids)], ["pmk_sale_order_id"], ["__count"])
        counts = {order.id: count for order, count in data}
        for order in self:
            order.pmk_task_count = counts.get(order.id, 0)

    # ─── Снимок прежней редакции — только для чтения ─────────────────────
    def write(self, vals):
        if not freeze_allowed(self.env) and SNAPSHOT_LOCKED_FIELDS & set(vals):
            for order in self:
                if order.pmk_is_revision:
                    raise snapshot_error(order)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _pmk_unlink_except_revision(self):
        if freeze_allowed(self.env):
            return
        for order in self:
            if order.pmk_is_revision:
                raise snapshot_error(order)

    def action_confirm(self):
        for order in self:
            if order.pmk_is_revision:
                raise snapshot_error(order)
        res = super().action_confirm()
        if not self.env.context.get(SKIP):
            self.filtered(lambda o: o.state == "sale")._pmk_after_confirm()
        return res

    def _pmk_after_confirm(self):
        """«Оплата пришла — в работу» = «Выиграно» на сделке.

        Сделка в работе и её можно менять — переводим в выигранные (там
        появится строка планировщика, crm_lead.py). Сделки нет, она уже
        выиграна или менять её нельзя — строка планировщика сразу. Права —
        того, кто подтвердил: чужую сделку не двигаем, как и отправка КП
        (pmk_deal/models/kp_sent.py).
        """
        for order in self:
            deal = order.opportunity_id
            if (deal and deal.active and deal.won_status == "pending"
                    and not deal.stage_id.is_won and deal.has_access("write")):
                deal.action_set_won()
                if order._pmk_planner_rows():
                    continue
            order._pmk_ensure_planner_row()

    # ─── Строка планировщика ────────────────────────────────────────────
    def _pmk_planner_rows(self):
        """Строки «Заказов в работе» этого счёта или его сделки (и архивные)."""
        self.ensure_one()
        domain = [("pmk_sale_order_id", "=", self.id)]
        if self.opportunity_id:
            domain = ["|", ("pmk_deal_id", "=", self.opportunity_id.id)] + domain
        return self.env["project.task"].sudo().with_context(active_test=False).search(domain)

    def _pmk_ensure_planner_row(self):
        """Ровно одна строка на действующий счёт: есть (даже в архиве) —
        только связываем со счётом, нет — заводим в «Очереди»."""
        Task = self.env["project.task"]
        rows = Task.browse()
        for order in self:
            if order.pmk_is_revision:
                continue
            found = order._pmk_planner_rows()
            if found:
                missing = found.filtered(lambda row: not row.pmk_sale_order_id)
                if missing:
                    missing.write({"pmk_sale_order_id": order.id})
                rows |= found
                continue
            rows |= Task._pmk_create_order_row(deal=order.opportunity_id, order=order)
        return rows

    # ─── Кнопки ─────────────────────────────────────────────────────────
    def action_open_planner_row(self):
        """Кнопка «Заказ»: строки нет — форма новой с данными счёта, одна —
        она сама, несколько — список."""
        self.ensure_one()
        rows = self.env["project.task"].search([("pmk_sale_order_id", "=", self.id)])
        action = self.env["project.task"]._pmk_rows_action(rows)
        if not rows:
            action["context"] = self.env["project.task"]._pmk_row_defaults(
                deal=self.opportunity_id, order=self)
        return action

    def action_open_spec(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "pmk.metal.spec",
            "res_id": self.pmk_spec_id.id,
            "views": [(False, "form")],
            "target": "current",
        }

    # ─── Счёт из расчёта ────────────────────────────────────────────────
    @api.model
    def _pmk_priced_products(self, spec):
        """Изделия с ценой клиенту — как в печати КП (без цены в КП не идут)."""
        return spec.product_ids.filtered(lambda product: product.price_customer_unit)

    @api.model
    def _pmk_spec_signature(self, spec, partner, org):
        """Что уходит клиенту: изделия (название, количество, цена), клиент,
        организация. Совпало с действующим счётом — редакция не нужна."""
        currency = spec.currency_id or self.env.company.currency_id
        rows = sorted(
            (product.id, (product.name or "").strip(), round(float(product.qty or 0), 3),
             currency.round(product.price_customer_unit))
            for product in self._pmk_priced_products(spec))
        return (tuple(rows), partner.id, org.id or False)

    def _pmk_signature(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        rows = sorted(
            (line.pmk_spec_product_id.id or 0, (line.name or "").strip(),
             round(line.product_uom_qty, 3), currency.round(line.price_unit))
            for line in self.order_line.filtered("pmk_from_spec"))
        return (tuple(rows), self.partner_id.id, self.pmk_org_id.id or False)

    @api.model
    def _pmk_service_product(self):
        template = self.env.ref("pmk_orders.product_mk_service", raise_if_not_found=False)
        return template.product_variant_id if template else self.env["product.product"]

    @api.model
    def _pmk_line_commands(self, spec):
        product = self._pmk_service_product()
        unit = self.env.ref("uom.product_uom_unit")
        commands = []
        for item in self._pmk_priced_products(spec):
            commands.append(Command.create({
                "product_id": product.id,
                "name": item.name,
                "product_uom_qty": item.qty,
                "product_uom_id": unit.id,
                # Цена задана явно: _compute_price_unit ядра считает её ручной
                # (technical_price_unit = 0 ≠ price_unit) и не перетрёт.
                "price_unit": item.price_customer_unit,
                "sequence": item.sequence,
                "pmk_spec_product_id": item.id,
                "pmk_from_spec": True,
            }))
        return commands

    @api.model
    def _pmk_create_from_spec(self, deal, spec, partner, org):
        vals = {
            "partner_id": partner.id,
            "opportunity_id": deal.id,
            "pmk_org_id": org.id or False,
            "pmk_spec_id": spec.id,
            "origin": spec.name,
            "company_id": (spec.company_id or deal.company_id or self.env.company).id,
            # Прайс-листы выключены, и счёт в валюте компании — валюте
            # расчёта. Пустой прайс-лист держит это и тогда, когда группу
            # прайс-листов включат (Default на боевой — в USD).
            "pricelist_id": False,
            "order_line": self._pmk_line_commands(spec),
        }
        if deal.user_id:
            vals["user_id"] = deal.user_id.id
        if deal.team_id:
            vals["team_id"] = deal.team_id.id
        if "sale_order_template_id" in self._fields:
            # Шаблон КП (sale_management) прислал бы клиенту письмо при
            # подтверждении — у счёта из расчёта шаблона нет.
            vals["sale_order_template_id"] = False
        # Без чужих default_* (контекст формы сделки, окна письма КП).
        order = self.sudo().with_context(clean_context(self.env.context)).with_context(
            mail_auto_subscribe_no_notify=True).create(vals)
        order.with_context(mail_auto_subscribe_no_notify=True).action_quotation_sent()
        return order

    def _pmk_mark_sent(self):
        """Черновик или отменённый — снова «Выставлен, ждём оплату»."""
        for order in self.with_context(mail_auto_subscribe_no_notify=True):
            if order.state in ("cancel", "sent"):
                if order.locked:
                    order.action_unlock()
                order.action_draft()
            if order.state == "draft":
                order.action_quotation_sent()

    def _pmk_snapshot_line_vals(self, line):
        return {
            "sequence": line.sequence,
            "display_type": line.display_type or False,
            "product_id": line.product_id.id or False,
            "name": line.name,
            "product_uom_qty": line.product_uom_qty,
            "product_uom_id": line.product_uom_id.id or False,
            "price_unit": line.price_unit,
            "technical_price_unit": line.technical_price_unit,
            "discount": line.discount,
            "tax_ids": [Command.set(line.tax_ids.ids)],
            "pmk_spec_product_id": line.pmk_spec_product_id.id or False,
            "pmk_from_spec": line.pmk_from_spec,
        }

    def _pmk_make_snapshot(self):
        """Прежняя редакция: копия явными значениями, отменена и заблокирована."""
        self.ensure_one()
        order = self.sudo()
        vals = {
            "name": order.name,
            "partner_id": order.partner_id.id,
            "partner_invoice_id": order.partner_invoice_id.id,
            "partner_shipping_id": order.partner_shipping_id.id,
            "pmk_org_id": order.pmk_org_id.id or False,
            "pmk_spec_id": order.pmk_spec_id.id or False,
            "pmk_is_revision": True,
            "pmk_revision": order.pmk_revision or 1,
            "pmk_revision_of_id": order.id,
            # Без сделки: снимок не считается счётом сделки (счётчики
            # sale_crm, «Связи», _pmk_current_invoice).
            "opportunity_id": False,
            "company_id": order.company_id.id,
            "date_order": order.date_order,
            "validity_date": order.validity_date,
            "user_id": order.user_id.id or False,
            "team_id": order.team_id.id or False,
            "pricelist_id": order.pricelist_id.id or False,
            "fiscal_position_id": order.fiscal_position_id.id or False,
            "payment_term_id": order.payment_term_id.id or False,
            "note": order.note,
            "origin": order.origin,
            "client_order_ref": order.client_order_ref,
            "order_line": [Command.create(self._pmk_snapshot_line_vals(line))
                           for line in order.order_line],
        }
        if "sale_order_template_id" in self._fields:
            vals["sale_order_template_id"] = False
        frozen = self.env["sale.order"].sudo().with_context(clean_context(self.env.context)).with_context(**{
            FREEZE: True, SKIP: True,
            "mail_create_nolog": True, "mail_create_nosubscribe": True,
            "mail_notrack": True, "mail_auto_subscribe_no_notify": True,
        })
        snapshot = frozen.create(vals)
        snapshot.write({"state": "cancel", "locked": True})
        snapshot._message_log(body=Markup(_(
            "Прежняя редакция счёта %(name)s (%(label)s): так он уходил клиенту до "
            "следующей редакции. Только для чтения.")) % {
                "name": order.name, "label": snapshot.pmk_revision_label})
        return snapshot

    def _pmk_new_revision(self, spec, partner, org):
        """Новая редакция действующего счёта: снимок прежней, строки изделий
        заново из расчёта, номер редакции +1, снова «Выставлен».

        Ручные строки (не из расчёта: доставка, скидка) не трогаем."""
        self.ensure_one()
        snapshot = self._pmk_make_snapshot()
        order = self.sudo().with_context(mail_auto_subscribe_no_notify=True)
        if order.locked:
            order.action_unlock()
        if order.state in ("sent", "cancel"):
            order.action_draft()
        order.order_line.filtered("pmk_from_spec").unlink()
        order.write({
            "partner_id": partner.id,
            "pmk_org_id": org.id or False,
            "pmk_spec_id": spec.id,
            "origin": spec.name,
            "pmk_revision": (order.pmk_revision or 1) + 1,
            # Дата редакции — сегодня: от неё налог режима (организация могла
            # перейти на УСН) и срок действия.
            "date_order": fields.Datetime.now(),
            "order_line": self._pmk_line_commands(spec),
        })
        order.action_quotation_sent()
        return snapshot
