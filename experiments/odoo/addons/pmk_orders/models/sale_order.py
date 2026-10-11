# -*- coding: utf-8 -*-
"""Счёт покупателю из расчёта и его жизнь (шаги З-2 08.10 и З-9 09.10.2026).

«Счёт покупателю» — штатный заказ клиента (sale.order), по-заводски (меню и
слова — pmk_theme). Для завода КП и счёт — один документ.

ЖИЗНЬ СЧЁТА (решения Антона 09.10.2026, шаг З-9; меняют схему З-2). «Счёт
как таковой создаётся на этапе расчёта, возможно меняется или дополняется, и
только когда окончательно сформировали, прописали условия, согласовали с
руководителем» — отправляется. «Автоотправки не нужны, перенос либо руками,
либо после нажатия на кнопку «Отправить КП»».

  Черновик ── «На согласование» ──▶ На согласовании ── «Согласовано» ──▶ Согласован
     ▲                                   │ «Вернуть на доработку»            │
     └───────────────────────────────────┘                                   │
  «Отправить КП» в расчёте / сделку перенесли в «КП отправлено» руками ──▶ Отправлен
  «Выиграно» / «Оплата пришла — в работу» ──▶ В работе (оплачен);  «Проиграно» ──▶ Отменён

  • Черновик заводит кнопка «Счёт» в расчёте (metal_spec.py): один счёт на
    сделку, повтор открывает тот же. Пока счёт не отправлен, его изделия идут
    вслед за расчётом сами — правка и сохранение расчёта пересобирают строки
    изделий черновика (без редакций); строки-услуги не трогаются.
  • Технически состояния — штатные draft / sent / sale / cancel (на них
    опираются ядро, планировщик, технический расчёт pmk_tech), согласование —
    своё поле pmk_approval. Состояние словами для людей — pmk_status.
  • Согласование — наблюдение, а не запрет: отправить можно и без отметки,
    тогда на счёте и в окне «Отправить КП» видно «не согласован». Правка
    согласованного счёта (или его расчёта) возвращает его в «Черновик».
  • Отправленный — зафиксирован: расчёт поменяли — на счёте плашка «расчёт
    изменился после отправки», при следующей «Отправить КП» — новая РЕДАКЦИЯ
    того же счёта («ред. 2»), прежняя хранится только для чтения. Условия,
    услуги и дата отправленного в форме закрыты (снимок обязан хранить то,
    что видел клиент); поменять их — кнопка «Новая редакция»: снимок, счёт
    снова черновик «ред. N+1», дальше обычный путь.
  • Задачи «Согласовать» / «Доработать» закрываются сами, когда больше не
    ждут: передан на согласование, отправлен, в работе, отменён.

СТРОКИ. Изделия расчёта — служебный товар-услуга «Изготовление
металлоконструкций» (data/product.xml), описание = название изделия,
количество, «шт», цена клиенту за штуку; строка помнит своё изделие
(pmk_spec_product_id) и что она из расчёта (pmk_from_spec). Такие строки в
счёте только для чтения — «две правды» (цена в счёте ≠ цене в расчёте) не
бывает: меняют в расчёте (sale_order_line.py держит это и на сервере).
Доставка, монтаж и прочее, чего в расчёте нет, — «Добавить услугу»: строка
свободным текстом с ценой (товар «Услуга»), правится и удаляется в счёте,
новая редакция её переносит как есть. Налог — режим организации на дату
счёта (pmk_org); компания — «цены включают налог»: сумма счёта = сумме КП.

РЕДАКЦИИ (шаг З-2). Действующий счёт остаётся той же записью (тот же номер,
ссылки из сделки, планировщика и ленты живы), счётчик pmk_revision растёт.
Прежняя редакция — СНИМОК: отдельный sale.order с тем же номером, собранный
явными значениями (price_unit и tax_ids — вычисляемые поля, copy() их не
переносит), отменён, заблокирован, без сделки (не попадает в счётчики
sale_crm и на схему «Связи»), со ссылкой на действующий. Снимок только для
чтения. Свои операции идут суперпользователем (sudo) с флагом контекста:
флаг без sudo не действует — контекст RPC-запроса задаёт браузер.

«ПОДТВЕРДИТЬ» = «ВЫИГРАНО». Кнопка подписана «Оплата пришла — в работу»:
подтверждение счёта переводит сделку в «Выиграно» (там появляется строка
планировщика). Писем не шлём: action_confirm без send_email, задачи
согласования — без письма о назначении (mail_activity_quick_update).
"""
import logging

from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare
from odoo.tools.misc import clean_context

_logger = logging.getLogger(__name__)

# Контекст: свои операции со снимками (создание, отмена, блокировка).
FREEZE = "pmk_revision_freeze"
# Контекст: не запускать связку сделка ↔ счёт ↔ планировщик (crm_lead.py).
SKIP = "pmk_orders_skip"
# Контекст (шаг З-9): свои операции со строками-изделиями (пересборка из
# расчёта, редакция). Как и FREEZE — только вместе с sudo.
SYNC = "pmk_spec_lines_sync"
# Контекст (шаг З-9): запись не сбрасывает «Согласован» (свои служебные записи).
KEEP_APPROVAL = "pmk_approval_keep"
# Контекст (шаг З-9): новая строка в счёте — «Добавить услугу».
ADD_SERVICE = "pmk_add_service"

APPROVER_GROUP = "pmk_orders.group_invoice_approver"
ACT_APPROVE = "pmk_orders.mail_activity_type_invoice_approve"
ACT_REWORK = "pmk_orders.mail_activity_type_invoice_rework"

APPROVAL = [
    ("none", "Не согласовывался"),
    ("pending", "На согласовании"),
    ("approved", "Согласован"),
]
STATUS = [
    ("draft", "Черновик"),
    ("approval", "На согласовании"),
    ("approved", "Согласован"),
    ("sent", "Отправлен"),
    ("sale", "В работе (оплачен)"),
    ("cancel", "Отменён"),
]
LEAD_FROM = [
    ("payment", "с момента оплаты"),
    ("drawings", "с момента согласования чертежей"),
    ("invoice", "с даты счёта"),
]
DELIVERY = [
    ("pickup", "Самовывоз"),
    ("delivery", "Доставка"),
]
# Условия счёта (шаг З-9): правятся в счёте, переносятся в новую редакцию
# (это та же запись) и хранятся в снимке.
TERMS_FIELDS = ("pmk_payment_note", "pmk_lead_days", "pmk_lead_from",
                "pmk_delivery", "pmk_delivery_address")
# Правка этих полей у согласованного черновика возвращает его в «Черновик».
APPROVAL_RESET_FIELDS = frozenset({
    "order_line", "partner_id", "pmk_org_id", "payment_term_id", "note", "pmk_spec_id",
    *TERMS_FIELDS,
})

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
    # Шаг З-9: условия, согласование, дата отправки.
    "pmk_approval", "pmk_sent_date", *TERMS_FIELDS,
})


def freeze_allowed(env):
    """Свои операции со снимком: sudo И флаг вместе (флаг один — от клиента)."""
    return bool(env.su and env.context.get(FREEZE))


def spec_lines_allowed(env):
    """Свои операции со строками-изделиями: sudo И флаг (пересборка, редакция,
    снимок)."""
    return bool(env.su and (env.context.get(SYNC) or env.context.get(FREEZE)))


def ru_env(records):
    """Записи с языком: события ленты (смена состояния, «Создано: …») пишутся
    словами языка окружения. Из браузера язык есть, из odoo shell и cron —
    нет, и в ленту легли бы «Quotation Sent → Sales Order»."""
    if records.env.context.get("lang"):
        return records
    return records.with_context(lang="ru_RU")


def money_text(env, amount, currency):
    """«9 500 000,00 ₽» — неразрывные пробелы, как в карточках сделки."""
    lang = env["res.lang"]._lang_get(env.lang or "ru_RU") or env["res.lang"]._lang_get("ru_RU")
    if lang:
        text = lang.format("%.2f", amount or 0.0, grouping=True)
    else:
        text = "%.2f" % (amount or 0.0)
    symbol = currency.symbol or ""
    return ("%s %s" % (text, symbol)).strip().replace(" ", " ")


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

    # ─── Шаг З-9: согласование и состояние словами ──────────────────────
    pmk_approval = fields.Selection(
        APPROVAL, "Согласование", default="none", required=True, copy=False,
        tracking=True,
        help="Руководитель смотрит счёт до отправки. Ничего не запрещает: отправить "
             "можно и без отметки — тогда на счёте видно «не согласован».")
    pmk_status = fields.Selection(
        STATUS, "Статус", compute="_compute_pmk_status", store=True, index=True,
        help="Черновик → На согласовании → Согласован → Отправлен → В работе (оплачен). "
             "Отправленным счёт становится по «Отправить КП» в расчёте или когда сделку "
             "переносят в «КП отправлено» руками.")
    pmk_sent_date = fields.Datetime(
        "Отправлен", copy=False, readonly=True,
        help="Когда счёт последний раз отмечен отправленным клиенту.")
    pmk_is_approver = fields.Boolean(compute="_compute_pmk_is_approver")

    # ─── Шаг З-9: условия ───────────────────────────────────────────────
    # Хранятся в счёте и печатаются (шаблон КП/счёта — шаг 62: готовые
    # строки pmk_lead_text и pmk_delivery_text).
    pmk_payment_note = fields.Char(
        "Оплата", tracking=True,
        help="Как платят, своими словами: «100% предоплата», «50% предоплата, 50% перед "
             "отгрузкой». Срок оплаты из списка — строкой выше.")
    pmk_lead_days = fields.Integer(
        "Срок изготовления, раб. дней", tracking=True,
        help="Рабочих дней на изготовление. 0 — срок не указан.")
    pmk_lead_from = fields.Selection(
        LEAD_FROM, "Срок считается", default="payment", tracking=True)
    pmk_lead_text = fields.Char(
        "Срок изготовления", compute="_compute_pmk_lead_text",
        help="Для печати: «20 раб. дней с момента оплаты».")
    pmk_delivery = fields.Selection(
        DELIVERY, "Доставка", tracking=True,
        help="Самовывоз со склада завода или доставка по адресу.")
    pmk_delivery_address = fields.Char(
        "Адрес доставки", tracking=True,
        help="Подставляется адрес доставки клиента — поправьте, если везём на объект.")
    pmk_delivery_text = fields.Char(
        "Доставка (для печати)", compute="_compute_pmk_delivery_text")

    # ─── Шаг З-9: сигналы и подписи (не хранятся) ───────────────────────
    pmk_tax_text = fields.Char(
        "Налог", compute="_compute_pmk_tax_text",
        help="Строка налога под итогом — как в КП: по режиму организации на дату счёта.")
    pmk_spec_changed_text = fields.Char(compute="_compute_pmk_spec_texts")
    pmk_skip_text = fields.Char(compute="_compute_pmk_spec_texts")
    pmk_lines_hint = fields.Char(compute="_compute_pmk_spec_texts")
    pmk_approval_signal = fields.Char(compute="_compute_pmk_approval_signal")

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

    @api.depends("state", "pmk_approval")
    def _compute_pmk_status(self):
        for order in self:
            if order.state == "draft":
                order.pmk_status = {"pending": "approval", "approved": "approved"}.get(
                    order.pmk_approval, "draft")
            else:
                order.pmk_status = order.state or "draft"

    @api.depends_context("uid")
    def _compute_pmk_is_approver(self):
        value = self.env.user.has_group(APPROVER_GROUP)
        for order in self:
            order.pmk_is_approver = value

    @api.depends("pmk_lead_days", "pmk_lead_from")
    def _compute_pmk_lead_text(self):
        labels = dict(LEAD_FROM)
        for order in self:
            if order.pmk_lead_days > 0:
                order.pmk_lead_text = ("%s раб. %s %s" % (
                    order.pmk_lead_days, _plural_days(order.pmk_lead_days),
                    labels.get(order.pmk_lead_from) or "")).strip()
            else:
                order.pmk_lead_text = False

    @api.depends("pmk_delivery", "pmk_delivery_address")
    def _compute_pmk_delivery_text(self):
        for order in self:
            if order.pmk_delivery == "pickup":
                order.pmk_delivery_text = "Самовывоз"
            elif order.pmk_delivery == "delivery":
                address = (order.pmk_delivery_address or "").strip()
                order.pmk_delivery_text = "Доставка: %s" % address if address else "Доставка"
            else:
                order.pmk_delivery_text = False

    @api.onchange("pmk_delivery")
    def _onchange_pmk_delivery(self):
        """Доставка — адрес доставки клиента одной строкой, если пусто."""
        for order in self:
            if order.pmk_delivery == "delivery" and not order.pmk_delivery_address:
                partner = order.partner_shipping_id or order.partner_id
                address = partner._display_address(without_company=True) if partner else ""
                order.pmk_delivery_address = ", ".join(
                    part.strip() for part in (address or "").splitlines() if part.strip()) or False

    @api.depends("amount_tax", "amount_total", "currency_id", "pmk_org_id", "date_order",
                 "company_id")
    def _compute_pmk_tax_text(self):
        for order in self:
            label, amount = order._pmk_tax_line()
            if amount is None:
                order.pmk_tax_text = label
            else:
                order.pmk_tax_text = "%s %s" % (
                    label, money_text(order.env, amount, order.currency_id))

    def _pmk_tax_line(self):
        """(подпись, сумма или None) — та же подпись, что в печати КП
        (pmk_bridge/tools/seller.tax_line по режиму организации на дату), сумма —
        фактический налог счёта (у услуг налог тот же, режим один на счёт)."""
        self.ensure_one()
        org = self.pmk_org_id
        if org:
            day = fields.Date.to_date(self.date_order) if self.date_order else fields.Date.context_today(self)
            label, printed = org._pmk_tax_line(day, self.amount_total, self.company_id)
            return label, (None if printed is None else self.amount_tax)
        currency = self.currency_id or self.company_id.currency_id or self.env.company.currency_id
        if currency.is_zero(self.amount_tax):
            return "Без НДС", None
        return "в том числе налог:", self.amount_tax

    @api.depends("state", "pmk_is_revision", "pmk_spec_id", "partner_id", "pmk_org_id",
                 "order_line.name", "order_line.product_uom_qty", "order_line.price_unit",
                 "order_line.pmk_from_spec", "pmk_revision")
    def _compute_pmk_spec_texts(self):
        for order in self:
            order.pmk_spec_changed_text = False
            order.pmk_skip_text = False
            order.pmk_lines_hint = False
            if order.pmk_is_revision or not order._origin.id:
                continue
            spec = order.pmk_spec_id.sudo()
            if order.state == "draft":
                order.pmk_lines_hint = _(
                    "Изделия идут вслед за расчётом: поправьте их в расчёте — черновик "
                    "обновится сам. Доставка, монтаж — «Добавить услугу».")
            elif order.state == "sent":
                order.pmk_lines_hint = _(
                    "Счёт отправлен: изделия, услуги и условия закрыты — так их видел клиент. "
                    "Изменить — «Новая редакция» (прежняя сохранится, счёт снова станет "
                    "черновиком) или поправьте расчёт и нажмите «Отправить КП» — уйдёт ред. %s.",
                    (order.pmk_revision or 1) + 1)
            if not spec:
                continue
            if order.state == "draft":
                skipped = spec.product_ids - self._pmk_priced_products(spec)
                if skipped:
                    order.pmk_skip_text = _(
                        "Без цены клиенту, в счёт не попали: %s", ", ".join(skipped.mapped("name")))
                continue
            if order.state not in ("sent", "sale"):
                continue
            deal = order.opportunity_id.sudo()
            partner = self._pmk_invoice_partner(deal, spec)
            org = spec.pmk_org_id or deal.pmk_org_id
            if self._pmk_spec_signature(spec, partner, org) == order._origin._pmk_signature():
                continue
            if order.state == "sale":
                order.pmk_spec_changed_text = _(
                    "Расчёт %s изменился после отправки — счёт в работе, в него изменения не "
                    "попадут.", spec.name)
            else:
                order.pmk_spec_changed_text = _(
                    "Расчёт %(spec)s изменился после отправки: в счёт войдёт ред. %(next)s при "
                    "«Отправить КП».", spec=spec.name, next=(order.pmk_revision or 1) + 1)

    @api.depends("state", "pmk_approval", "pmk_is_revision")
    def _compute_pmk_approval_signal(self):
        for order in self:
            if (not order.pmk_is_revision and order.state in ("sent", "sale")
                    and order.pmk_approval != "approved"):
                order.pmk_approval_signal = _("Отправлен без согласования")
            else:
                order.pmk_approval_signal = False

    # ─── Запись: снимок только для чтения, согласование, отправка ───────
    def write(self, vals):
        if not freeze_allowed(self.env) and SNAPSHOT_LOCKED_FIELDS & set(vals):
            for order in self:
                if order.pmk_is_revision:
                    raise snapshot_error(order)
        if vals.get("state") == "sent" and "pmk_sent_date" not in vals:
            vals = dict(vals, pmk_sent_date=fields.Datetime.now())
        reset = self.browse()
        if (not self.env.context.get(KEEP_APPROVAL) and "pmk_approval" not in vals
                and APPROVAL_RESET_FIELDS & set(vals)):
            reset = self.filtered(lambda o: o.state == "draft" and o.pmk_approval == "approved"
                                  and not o.pmk_is_revision)
        newly_sent = closing = self.browse()
        if vals.get("state") == "sent":
            newly_sent = self.filtered(lambda o: o.state != "sent" and not o.pmk_is_revision)
        elif vals.get("state") in ("sale", "cancel"):
            # В работу или отменён — в т. ч. прямо из черновика («Выиграно»,
            # «Оплата пришла», «Отмена»), мимо «Отправлен».
            closing = self.filtered(lambda o: o.state != vals["state"] and not o.pmk_is_revision)
        res = super().write(vals)
        if reset:
            reset._pmk_reset_approval(_(
                "Счёт изменён после согласования — снова «Черновик»: согласуйте заново."))
        if newly_sent:
            newly_sent._pmk_after_sent()
        if closing:
            closing._pmk_close_approval(vals["state"])
        return res

    def create_document_from_attachment(self, attachment_ids):
        """Счёт из файла (PDF/XML вставкой Ctrl+V или перетаскиванием в
        список и канбан счетов — зона ядра рисуется и без «Новое») — нет:
        счёт рождается кнопкой «Счёт» в расчёте (шаг З-9). Иначе появлялся бы
        черновик без сделки и расчёта, клиентом — сам пользователь.
        Вернуть — убрать метод (docs/disabled-features.md, шаг З-9)."""
        raise UserError(_(
            "Счёт покупателю из файла не заводится: черновик — кнопкой «Счёт» в расчёте "
            "сделки. Файл клиента приложите к сделке или к расчёту."))

    def _pmk_reset_approval(self, text):
        for order in self:
            if order.pmk_approval == "none":
                continue
            order.sudo().with_context(**{KEEP_APPROVAL: True}).write({"pmk_approval": "none"})
            order._pmk_note(text)

    def _pmk_after_sent(self):
        """Счёт ушёл клиенту: несогласованная задача «Согласовать» больше не
        ждёт — закрыта с отзывом; «На согласовании» → без отметки (пометка
        «Отправлен без согласования» видна на счёте). Задача «Доработать
        счёт» — тоже закрыта: доработанный ушёл."""
        for order in self:
            if order.pmk_approval == "pending":
                order.sudo().with_context(**{KEEP_APPROVAL: True}).write({"pmk_approval": "none"})
            order.sudo().activity_feedback(
                [ACT_APPROVE], feedback=_("Счёт отправлен клиенту без отметки «Согласовано»."))
            order.sudo().activity_feedback(
                [ACT_REWORK], feedback=_("Счёт отправлен клиенту."))

    def _pmk_close_approval(self, state):
        """Счёт в работе или отменён: задачи «Согласовать» и «Доработать»
        больше не ждут — закрыты с отзывом; «На согласовании» → без отметки
        (у счёта в работе видно «Отправлен без согласования»)."""
        text = (_("Счёт в работу — согласование больше не ждёт.") if state == "sale"
                else _("Счёт отменён — согласование больше не ждёт."))
        for order in self:
            if order.pmk_approval == "pending":
                order.sudo().with_context(**{KEEP_APPROVAL: True}).write({"pmk_approval": "none"})
            order.sudo().activity_feedback([ACT_APPROVE, ACT_REWORK], feedback=text)

    def _pmk_note(self, text):
        """Заметка в ленту счёта — без уведомлений подписчикам."""
        body = text if isinstance(text, Markup) else escape(text)
        for order in self:
            order.sudo()._message_log(body=body)

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
        res = super(SaleOrder, ru_env(self)).action_confirm()
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
                # Шаг З-15: сдача пуста и руками не правилась — от срока счёта.
                found.filtered(lambda row: row.pmk_sale_order_id == order)._pmk_fill_plan_dates()
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
        """Кнопка-счётчик «Расчёт» и «Изменить в расчёте» (шаг З-9)."""
        self.ensure_one()
        if not self.pmk_spec_id:
            raise UserError(_("У счёта нет расчёта: изделия в нём заведены руками."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "pmk.metal.spec",
            "res_id": self.pmk_spec_id.id,
            "views": [(False, "form")],
            "target": "current",
        }

    def action_pmk_send_kp(self):
        """«Отправить КП» в счёте — то же окно письма, что у расчёта: КП уходит
        из расчёта счёта, после отправки счёт сам станет «Отправлен»."""
        self.ensure_one()
        if not self.pmk_spec_id:
            raise UserError(_("У счёта нет расчёта — КП отправляют из расчёта."))
        return self.pmk_spec_id.action_send_quotation()

    def action_pmk_new_revision(self):
        """«Новая редакция» у отправленного счёта (шаг З-9): поменять условия
        или услуги после отправки. Прежнее содержание — снимком (так счёт
        видел клиент), счёт — снова черновик «ред. N+1»: условия и услуги
        правятся, изделия идут за расчётом, согласование заново. Отправленным
        он станет, как обычно, по «Отправить КП»."""
        self.ensure_one()
        if self.pmk_is_revision:
            raise snapshot_error(self)
        if self.state != "sent":
            raise UserError(_(
                "Новая редакция — у отправленного счёта: черновик правится и так."))
        self.check_access("write")
        spec = self.pmk_spec_id.sudo()
        if not spec:
            raise UserError(_("У счёта нет расчёта — новую редакцию не собрать."))
        deal = self.opportunity_id.sudo() or spec.opportunity_id
        partner = self._pmk_invoice_partner(deal, spec)
        if not partner or not self._pmk_priced_products(spec):
            raise UserError(_(
                "В расчёте %s нет клиента или цены клиенту ни у одного изделия — "
                "новую редакцию не собрать.", spec.name))
        org = spec.pmk_org_id or deal.pmk_org_id
        snapshot = self._pmk_new_revision(spec, partner, org, send=False)
        self._pmk_note(_(
            "Новая редакция %(label)s — снова черновик: условия и услуги правятся, изделия "
            "идут за расчётом. Прежняя (%(old)s) сохранена только для чтения.",
            label=self.pmk_revision_label, old=snapshot.pmk_revision_label))
        return self._pmk_form_action()

    def action_pmk_to_approval(self):
        """«На согласование»: руководителю — задача «Согласовать счёт» (без
        письма), в ленте — заметка. Ничего не блокирует."""
        for order in self:
            if order.pmk_is_revision:
                raise snapshot_error(order)
            if order.state != "draft":
                raise UserError(_(
                    "%s уже отправлен клиенту — согласуют черновик.", order.display_name))
            if order.pmk_approval != "none":
                continue
            approver = order._pmk_approver()
            order.sudo().with_context(**{KEEP_APPROVAL: True}).write({"pmk_approval": "pending"})
            # Доработали и снова на согласование — задача «Доработать» сделана.
            order.sudo().activity_feedback(
                [ACT_REWORK], feedback=_("Доработан и передан на согласование."))
            if approver:
                order.sudo().with_context(mail_activity_quick_update=True).activity_schedule(
                    ACT_APPROVE, user_id=approver.id,
                    note=_("Счёт %(name)s на %(total)s ждёт согласования. Менеджер — %(user)s.",
                           name=order.display_name,
                           total=money_text(order.env, order.amount_total, order.currency_id),
                           user=self.env.user.name))
                order._pmk_note(_("Передан на согласование: %s.", approver.name))
            else:
                order._pmk_note(_(
                    "Передан на согласование, но согласующего нет: дайте кому-нибудь "
                    "группу «Руководитель: согласует счета»."))
        return True

    def _pmk_approver(self):
        """Кому согласовывать: руководитель команды продаж счёта, если он
        согласующий, иначе первый согласующий."""
        self.ensure_one()
        group = self.env.ref(APPROVER_GROUP, raise_if_not_found=False)
        if not group:
            return self.env["res.users"]
        users = group.sudo().all_user_ids.filtered(lambda u: u.active and not u.share)
        leader = self.team_id.sudo().user_id
        if leader and leader in users:
            return leader
        return users.sorted("id")[:1]

    def _pmk_check_approver(self):
        if not self.env.user.has_group(APPROVER_GROUP):
            raise AccessError(_(
                "Согласует счета руководитель (группа «Руководитель: согласует счета»)."))

    def action_pmk_approve(self):
        """«Согласовано» — только руководителю (проверка на сервере)."""
        self._pmk_check_approver()
        for order in self:
            if order.pmk_is_revision:
                raise snapshot_error(order)
            if order.state != "draft":
                raise UserError(_("%s уже отправлен клиенту.", order.display_name))
            if order.pmk_approval == "approved":
                continue
            order.sudo().with_context(**{KEEP_APPROVAL: True}).write({"pmk_approval": "approved"})
            order.sudo().activity_feedback([ACT_APPROVE], feedback=_("Согласовано."))
            order._pmk_note(_("Согласовано: %s.", self.env.user.name))
        return True

    def action_pmk_return(self):
        """«Вернуть на доработку» — окно с обязательным комментарием."""
        self._pmk_check_approver()
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Вернуть на доработку"),
            "res_model": "pmk.orders.return.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def _pmk_return_to_rework(self, comment):
        self._pmk_check_approver()
        for order in self:
            if order.state != "draft":
                raise UserError(_("%s уже отправлен клиенту.", order.display_name))
            order.sudo().with_context(**{KEEP_APPROVAL: True}).write({"pmk_approval": "none"})
            order.sudo().activity_feedback(
                [ACT_APPROVE], feedback=_("Вернул на доработку: %s", comment))
            manager = order.user_id or order.create_uid
            if manager:
                order.sudo().with_context(mail_activity_quick_update=True).activity_schedule(
                    ACT_REWORK, user_id=manager.id, note=comment)
            order._pmk_note(_("Вернул на доработку (%(user)s): %(comment)s",
                              user=self.env.user.name, comment=comment))
        return True

    # ─── Счёт из расчёта ────────────────────────────────────────────────
    @api.model
    def _pmk_priced_products(self, spec):
        """Изделия с ценой клиенту — как в печати КП (без цены в КП не идут)."""
        return spec.product_ids.filtered(lambda product: product.price_customer_unit)

    @api.model
    def _pmk_invoice_partner(self, deal, spec):
        """Клиент счёта — компания клиента сделки, иначе расчёта."""
        return (deal.partner_id or spec.partner_id).commercial_partner_id

    @api.model
    def _pmk_spec_signature(self, spec, partner, org):
        """Что уходит клиенту: изделия (название, количество, цена), клиент,
        организация. Совпало с действующим счётом — редакция не нужна.
        Услуги (строки не из расчёта) в подпись не входят."""
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
    def _pmk_extra_service_product(self):
        """Товар строк «Добавить услугу» (шаг З-9): доставка, монтаж и прочее."""
        template = self.env.ref("pmk_orders.product_extra_service", raise_if_not_found=False)
        return template.sudo().product_variant_id.with_env(self.env) if template \
            else self.env["product.product"]

    @api.model
    def _pmk_line_vals(self, item):
        return {
            "product_id": self._pmk_service_product().id,
            "name": item.name,
            "product_uom_qty": item.qty,
            "product_uom_id": self.env.ref("uom.product_uom_unit").id,
            # Цена — ручная для ядра: _compute_price_unit (зависит от
            # количества) не перетирает цену, если technical_price_unit ≠
            # price_unit. Без явного 0 ядро при создании ставит technical =
            # price (sale_order_line._add_precomputed_values), и смена одного
            # количества в расчёте сбросила бы цену в цену товара — 0 ₽.
            "price_unit": item.price_customer_unit,
            "technical_price_unit": 0.0,
            "sequence": item.sequence,
            "pmk_spec_product_id": item.id,
            "pmk_from_spec": True,
        }

    @api.model
    def _pmk_line_commands(self, spec):
        return [Command.create(self._pmk_line_vals(item))
                for item in self._pmk_priced_products(spec)]

    def _pmk_sync_line_commands(self, spec):
        """Строки-изделия черновика = изделия расчёта с ценой: совпавшие по
        изделию правятся на месте, новые заводятся, лишние удаляются. Строки не
        из расчёта (услуги) не трогаются."""
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        wanted = {item.id: item for item in self._pmk_priced_products(spec)}
        commands, seen = [], set()
        for line in self.order_line.filtered("pmk_from_spec"):
            item = line.pmk_spec_product_id
            if item.id not in wanted or item.id in seen:
                commands.append(Command.delete(line.id))
                continue
            seen.add(item.id)
            vals = {}
            if (line.name or "") != (item.name or ""):
                vals["name"] = item.name
            if float_compare(line.product_uom_qty, item.qty, precision_digits=3):
                vals["product_uom_qty"] = item.qty
            if (currency.compare_amounts(line.price_unit, item.price_customer_unit)
                    or "product_uom_qty" in vals or line.technical_price_unit):
                # Цена пишется вместе с количеством: записанное поле ядро в
                # том же проходе не пересчитывает; technical = 0 — цена
                # остаётся «ручной» и дальше (и у строк, заведённых до
                # исправления, где technical = price).
                vals["price_unit"] = item.price_customer_unit
                vals["technical_price_unit"] = 0.0
            if line.sequence != item.sequence:
                vals["sequence"] = item.sequence
            if vals:
                commands.append(Command.update(line.id, vals))
        commands += [Command.create(self._pmk_line_vals(item))
                     for item_id, item in wanted.items() if item_id not in seen]
        return commands

    @api.model
    def _pmk_create_from_spec(self, deal, spec, partner, org):
        """Черновик счёта из расчёта (шаг З-9: отправленным его делает
        _pmk_mark_sent — «Отправить КП» или перенос сделки руками)."""
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
        Order = ru_env(self.sudo().with_context(clean_context(self.env.context)))
        return Order.with_context(mail_auto_subscribe_no_notify=True).create(vals)

    def _pmk_sync_from_spec(self, spec=None):
        """Черновик идёт за расчётом: строки-изделия, клиент, организация, сам
        расчёт (переключение на другой расчёт сделки). Вернёт True, если
        изменилось то, что уходит клиенту. Согласованный черновик — снова
        «Черновик» с заметкой."""
        self.ensure_one()
        order = ru_env(self.sudo().with_context(**{
            SYNC: True, KEEP_APPROVAL: True, SKIP: True,
            "mail_auto_subscribe_no_notify": True}))
        spec = (spec or order.pmk_spec_id).sudo()
        if not spec or order.state != "draft" or order.pmk_is_revision:
            return False
        before = order._pmk_signature()
        deal = order.opportunity_id or spec.opportunity_id
        partner = self._pmk_invoice_partner(deal, spec)
        org = spec.pmk_org_id or deal.pmk_org_id
        vals = {}
        if partner and order.partner_id != partner:
            # Смена клиента пересчитала бы срок оплаты и прайс-лист (ядро):
            # срок — выбранный менеджером, прайс-листа нет (валюта компании).
            vals.update(partner_id=partner.id, pricelist_id=False,
                        payment_term_id=order.payment_term_id.id or False)
        if org and order.pmk_org_id != org:
            vals["pmk_org_id"] = org.id
        if order.pmk_spec_id != spec:
            vals.update(pmk_spec_id=spec.id, origin=spec.name)
        commands = order._pmk_sync_line_commands(spec)
        if commands:
            vals["order_line"] = commands
        if vals:
            order.write(vals)
        changed = order._pmk_signature() != before
        if changed and order.pmk_approval == "approved":
            order._pmk_reset_approval(_(
                "Расчёт %s изменён после согласования — счёт снова «Черновик»: согласуйте "
                "заново.", spec.name))
        return changed

    def _pmk_mark_sent(self, note=None):
        """Черновик или отменённый — «Отправлен»."""
        for order in ru_env(self.sudo().with_context(mail_auto_subscribe_no_notify=True)):
            if order.state in ("cancel", "sent"):
                if order.locked:
                    order.action_unlock()
                order.action_draft()
            if order.state == "draft":
                order.action_quotation_sent()
            if note:
                order._pmk_note(note)

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
            # Шаг З-9: условия и согласование — как уходили клиенту.
            "pmk_approval": order.pmk_approval,
            "pmk_sent_date": order.pmk_sent_date,
            **{name: order[name] for name in TERMS_FIELDS},
            "order_line": [Command.create(self._pmk_snapshot_line_vals(line))
                           for line in order.order_line],
        }
        if "sale_order_template_id" in self._fields:
            vals["sale_order_template_id"] = False
        frozen = ru_env(self.env["sale.order"].sudo().with_context(
            clean_context(self.env.context))).with_context(**{
                FREEZE: True, SKIP: True, KEEP_APPROVAL: True,
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

    def _pmk_new_revision(self, spec, partner, org, send=True):
        """Новая редакция действующего счёта: снимок прежней, строки изделий
        заново из расчёта, номер редакции +1, снова «Отправлен» (send) или
        «Черновик».

        Строки-услуги (не из расчёта: доставка, монтаж) переносятся как есть.
        Согласование относилось к прошлой редакции — сбрасывается."""
        self.ensure_one()
        snapshot = self._pmk_make_snapshot()
        order = ru_env(self.sudo().with_context(**{
            SYNC: True, KEEP_APPROVAL: True, "mail_auto_subscribe_no_notify": True}))
        if order.locked:
            order.action_unlock()
        if order.state in ("sent", "cancel"):
            order.action_draft()
        order.order_line.filtered("pmk_from_spec").unlink()
        vals = {
            "pmk_org_id": org.id or False,
            "pmk_spec_id": spec.id,
            "origin": spec.name,
            "pmk_revision": (order.pmk_revision or 1) + 1,
            "pmk_approval": "none",
            # Дата редакции — сегодня: от неё налог режима (организация могла
            # перейти на УСН) и срок действия.
            "date_order": fields.Datetime.now(),
            "order_line": self._pmk_line_commands(spec),
        }
        if order.partner_id != partner:
            vals.update(partner_id=partner.id, pricelist_id=False,
                        payment_term_id=order.payment_term_id.id or False)
        order.write(vals)
        order.activity_unlink([ACT_APPROVE])
        if send:
            order.action_quotation_sent()
        return snapshot

    def _pmk_reopen_draft(self, spec, partner, org):
        """Отменённый счёт сделки в работе — снова «Черновик» из расчёта
        (кнопка «Счёт» в расчёте). Уже уходил клиенту и расчёт с тех пор
        изменился — прежнее содержание сохраняется редакцией (как при
        «Отправить КП»)."""
        self.ensure_one()
        wanted = self._pmk_spec_signature(spec, partner, org)
        if self.pmk_sent_date and self._pmk_signature() != wanted:
            self._pmk_new_revision(spec, partner, org, send=False)
            return self
        order = ru_env(self.sudo().with_context(mail_auto_subscribe_no_notify=True))
        if order.locked:
            order.action_unlock()
        order.action_draft()
        self._pmk_sync_from_spec(spec)
        return self

    def _pmk_form_action(self):
        """Форма счёта (из кнопок расчёта и сделки): без «Новое»."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "sale.order",
            "res_id": self.id,
            "views": [(self.env.ref("sale.view_order_form").id, "form")],
            "target": "current",
            "context": {"create": False},
        }


def _plural_days(n):
    """«день / дня / дней» к числу: «1 раб. день», «3 раб. дня», «20 раб. дней»."""
    n = abs(int(n or 0))
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"
