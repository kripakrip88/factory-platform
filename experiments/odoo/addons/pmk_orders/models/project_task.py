# -*- coding: utf-8 -*-
"""Строка планировщика «Заказы в работе» — задача штатного проекта (шаг З-2).

Колонки — как в Excel-планировщике Антона: Компания, Описание заказа, Дата
старта (план), Дата сдачи (план), Статус (этап), Ответственный, Сумма заказа,
№ счёта, Дата оплаты, Сумма оплаты, % оплаты, Дата готовности, Дата отгрузки
факт, Доп. инфо, Заказано?, Краска, Паспорт; плюс Счёт покупателю, Сделка,
Наша организация и Металл. Все поля — с префиксом pmk_ и видны только в
видах планировщика: задачам «Доработки» и «Списка дел» они не мешают.

СТРОКА ПОЯВЛЯЕТСЯ САМА, когда сделку переводят в «Выиграно» (crm_lead.py) или
подтверждают счёт («Оплата пришла — в работу», sale_order.py). Ровно одна на
счёт и сделку: уже есть, даже в архиве, — новая не заводится. Автосоздание —
от sudo и без письма «Вам назначена задача» (у всех уведомления по почте).

СУММА — из счёта (amount_total) и меняется с его редакцией. Без счёта (будущий
импорт из Excel, карточка 3) — правится руками и не затирается. «№ счёта»,
сумма и дата оплаты — пока руками (потом МойСклад); % оплаты считается.

«СДАЧА (ПЛАН)» — своё поле Date, а не штатный срок date_deadline (Datetime):
в Excel даты без времени, импорт без сдвига часового пояса, «просрочена»
проще. Штатный срок остаётся «Доработке» и «Списку дел».
"""
from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.tools.misc import clean_context

ORDERED = [("yes", "Да"), ("no", "Нет")]
# «Получен частично» — шаг З-5 (pmk_tech, «Материал пришёл»): пришла часть
# заявок на металл заказа. Новое значение в varchar — миграции не нужно.
METAL = [("none", "—"), ("wait", "Ждём"), ("part", "Получен частично"), ("got", "Получен")]


class ProjectTask(models.Model):
    _inherit = "project.task"

    pmk_is_order = fields.Boolean(related="project_id.pmk_is_orders", string="Строка заказа")
    pmk_stage_code = fields.Selection(related="stage_id.pmk_order_stage", string="Смысл этапа")
    pmk_sale_order_id = fields.Many2one(
        "sale.order", "Счёт покупателю", index=True, ondelete="set null", copy=False,
        tracking=True, domain="[('pmk_is_revision', '=', False)]",
        help="Счёт покупателю, по которому работаем. Сумма строки — из него.")
    pmk_deal_id = fields.Many2one(
        "crm.lead", "Сделка", index=True, ondelete="set null", copy=False, tracking=True,
        domain="[('type', '=', 'opportunity')]")
    pmk_deal_number = fields.Char(related="pmk_deal_id.pmk_number", string="Номер сделки")
    pmk_org_id = fields.Many2one(
        "pmk.org", "Наша организация", compute="_compute_pmk_org_id", store=True,
        readonly=False, ondelete="set null",
        help="Из счёта покупателю; без счёта — руками.")
    pmk_date_start = fields.Date("Старт (план)")
    pmk_date_due = fields.Date("Сдача (план)", tracking=True)
    pmk_currency_id = fields.Many2one(
        "res.currency", "Валюта", compute="_compute_pmk_currency_id", store=True)
    pmk_amount = fields.Monetary(
        "Сумма заказа", currency_field="pmk_currency_id",
        compute="_compute_pmk_amount", store=True, readonly=False, tracking=True,
        help="Итог счёта покупателю (с налогом). Без счёта — руками.")
    pmk_invoice = fields.Char("№ счёта", help="Номер счёта из МоегоСклада, бывает «Нал». Пока руками.")
    pmk_paid_date = fields.Date("Дата оплаты")
    pmk_paid_amount = fields.Monetary(
        "Сумма оплаты", currency_field="pmk_currency_id", tracking=True)
    pmk_paid_pct = fields.Float(
        "Оплачено, %", compute="_compute_pmk_paid_pct", store=True, digits=(6, 0),
        aggregator=None, help="Сумма оплаты от суммы заказа. Сумма 0 — 0 %.")
    pmk_ready_date = fields.Date("Дата готовности")
    pmk_ship_date = fields.Date("Дата отгрузки (факт)")
    pmk_note = fields.Text("Доп. инфо")
    pmk_ordered = fields.Selection(ORDERED, "Заказано?")
    pmk_paint = fields.Char("Краска")
    pmk_passport = fields.Boolean("Паспорт")
    pmk_metal = fields.Selection(
        METAL, "Металл", tracking=True,
        help="«Ждём» ставит «Заявка на металл» из технического расчёта (шаг З-4, "
             "pmk_tech); «Получен» / «Получен частично» — кнопка «Материал пришёл» "
             "в заказе поставщику (шаг З-5): пришли все заявки на металл заказа или "
             "часть. Строке без заявок — руками.")
    pmk_overdue = fields.Boolean(
        "Просрочена сдача", compute="_compute_pmk_overdue", search="_search_pmk_overdue",
        help="Сдача (план) прошла, а заказ не отгружен. Сигнал, ничего не запрещает.")

    @api.depends("pmk_sale_order_id.pmk_org_id")
    def _compute_pmk_org_id(self):
        for task in self:
            if task.pmk_sale_order_id:
                task.pmk_org_id = task.pmk_sale_order_id.pmk_org_id
            # Без счёта — не трогаем: поле руками (как и сумма ниже).

    @api.depends("company_id")
    def _compute_pmk_currency_id(self):
        for task in self:
            task.pmk_currency_id = task.company_id.currency_id or task.env.company.currency_id

    @api.depends("pmk_sale_order_id.amount_total")
    def _compute_pmk_amount(self):
        for task in self:
            if task.pmk_sale_order_id:
                task.pmk_amount = task.pmk_sale_order_id.amount_total

    @api.depends("pmk_amount", "pmk_paid_amount")
    def _compute_pmk_paid_pct(self):
        for task in self:
            task.pmk_paid_pct = (
                (task.pmk_paid_amount or 0.0) / task.pmk_amount * 100.0 if task.pmk_amount else 0.0)

    @api.depends("pmk_date_due", "pmk_ship_date", "stage_id.pmk_order_stage")
    @api.depends_context("tz")
    def _compute_pmk_overdue(self):
        today = fields.Date.context_today(self)
        for task in self:
            task.pmk_overdue = bool(
                task.pmk_date_due and task.pmk_date_due < today and not task.pmk_ship_date
                and task.stage_id.pmk_order_stage != "shipped")

    def _search_pmk_overdue(self, operator, value):
        if operator in ("=", "!="):
            chosen = {bool(value)}
        elif operator in ("in", "not in"):
            chosen = {bool(item) for item in value}
        else:
            return NotImplemented
        if operator in ("!=", "not in"):
            chosen = {True, False} - chosen
        overdue = [
            "&", "&",
            ("pmk_date_due", "<", fields.Date.context_today(self)),
            ("pmk_ship_date", "=", False),
            ("stage_id.pmk_order_stage", "!=", "shipped"),
        ]
        if chosen == {True, False}:
            return []
        if not chosen:
            return [("id", "in", [])]
        return overdue if True in chosen else ["!"] + overdue

    def get_formview_id(self, access_uid=None):
        """Строка заказа открывается компактной формой планировщика отовсюду:
        из сделки, ленты, «Связей». Задачи других проектов — штатной."""
        if len(self) == 1 and self.pmk_is_order:
            view = self.env.ref("pmk_orders.view_task_order_form", raise_if_not_found=False)
            if view:
                return view.id
        return super().get_formview_id(access_uid=access_uid)

    # ─── Создание строки ────────────────────────────────────────────────
    @api.model
    def _pmk_orders_project(self):
        project = self.env.ref("pmk_orders.project_orders", raise_if_not_found=False)
        if not project:
            project = self.env["project.project"].sudo().with_context(active_test=False).search(
                [("pmk_is_orders", "=", True)], limit=1)
        return project.sudo()

    @api.model
    def _pmk_queue_stage(self, project):
        stages = project.type_ids.sorted("sequence")
        return (stages.filtered(lambda stage: stage.pmk_order_stage == "queue")[:1]
                or stages.filtered(lambda stage: not stage.fold)[:1])

    @api.model
    def _pmk_row_values(self, deal=None, order=None):
        """Что знает новая строка: из сделки и счёта (оба могут быть пусты)."""
        order = (order or self.env["sale.order"]).sudo()
        deal = (deal or order.opportunity_id or self.env["crm.lead"]).sudo()
        project = self._pmk_orders_project()
        stage = self._pmk_queue_stage(project)
        partner = (order.partner_id or deal.partner_id).commercial_partner_id
        user = deal.user_id or order.user_id
        name = deal.name or order.pmk_spec_id.note or order.name or _("Заказ")
        vals = {
            "name": name,
            "project_id": project.id,
            "stage_id": stage.id or False,
            "partner_id": partner.id or False,
            "pmk_deal_id": deal.id or False,
            "pmk_sale_order_id": order.id or False,
            "pmk_metal": "none",
        }
        if user:
            vals["user_ids"] = [Command.set(user.ids)]
        if not order and deal:
            # Без счёта — цена клиенту сделки (из её расчёта), дальше руками.
            vals["pmk_amount"] = deal.expected_revenue
        return vals

    @api.model
    def _pmk_create_order_row(self, deal=None, order=None):
        if not self._pmk_orders_project():
            return self.browse()
        vals = self._pmk_row_values(deal=deal, order=order)
        # Без чужих default_* (контекст формы сделки или воронки): строка
        # получает только свои значения.
        row = self.sudo().with_context(clean_context(self.env.context)).with_context(
            mail_auto_subscribe_no_notify=True, mail_create_nolog=True,
            default_project_id=vals["project_id"]).create(vals)
        links = [rec._get_html_link() for rec in (row.pmk_deal_id, row.pmk_sale_order_id) if rec]
        if links:
            row._message_log(body=Markup(_("Заказ в работе появился сам: %s.")) % Markup(", ").join(links))
        return row.with_env(self.env)

    @api.model
    def _pmk_row_defaults(self, deal=None, order=None):
        """Контекст новой строки из кнопки «Заказ» (сделка или счёт)."""
        vals = self._pmk_row_values(deal=deal, order=order)
        ctx = {"default_%s" % key: value for key, value in vals.items() if key != "user_ids"}
        user = (deal.user_id if deal else False) or (order.user_id if order else False)
        if user:
            ctx["default_user_ids"] = user.ids
        return ctx

    @api.model
    def _pmk_rows_action(self, rows):
        """Окно строк: нет — форма новой, одна — она, несколько — список."""
        form = self.env.ref("pmk_orders.view_task_order_form").id
        listing = self.env.ref("pmk_orders.view_task_order_list").id
        action = {
            "type": "ir.actions.act_window",
            "name": _("Заказы в работе"),
            "res_model": "project.task",
            "target": "current",
            "context": {},
        }
        if not rows:
            action.update(name=_("Новый заказ в работе"), views=[(form, "form")])
        elif len(rows) == 1:
            action.update(name=rows.name, res_id=rows.id, views=[(form, "form")])
        else:
            action.update(views=[(listing, "list"), (form, "form")],
                          domain=[("id", "in", rows.ids)])
        return action
