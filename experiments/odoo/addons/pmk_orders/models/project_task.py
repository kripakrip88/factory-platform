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

ШАГ З-15 (11.10.2026, карточка 15; прогон Кытмановой 09.10: строка
называлась темой письма, сдача пустая при «15 раб. дней с момента оплаты»):
  • НАЗВАНИЕ новой строки — «Предмет КП» расчёта счёта (note); пусто — имя
    первого изделия расчёта и «+N» остальных; нет расчёта — имя сделки, как
    было; нет и сделки — номер счёта. Клиент — своим полем. Уже заведённые
    строки не переименовываются.
  • СТАРТ И СДАЧА (ПЛАН) — из срока изготовления счёта (pmk_lead_days,
    pmk_lead_from): рабочие дни календаря компании (пн–пт и «Общие
    выходные» — праздники заводятся там), день события не считается.
    «С момента оплаты» — от дня «Выиграно», а когда впервые внесут дату
    оплаты — пересчёт от неё; «с даты счёта» — от дня отправки счёта (дату
    счёта ядро переписывает при подтверждении); «с согласования чертежей» —
    не считаем, подсказка в ленте строки. Откуда дата — заметкой в ленте.
  • РУЧНАЯ ПРАВКА сдачи — флаг pmk_date_due_manual: дальше сама не
    меняется. Очистка — тоже ручная правка: сдача остаётся пустой (срок
    неизвестен — ждут чертежи), в ленте — какой была бы расчётная дата.
    Вторая оплата и правка даты оплаты сдачу не двигают.
  • ГАРАНТИЙНОЕ ПИСЬМО (pmk_guarantee) — срок от «Старт (план)» = день
    письма: галочка в строке или правка старта у такой строки пересчитывают
    сдачу; дата оплаты её больше не двигает.
  • ОКНО «ОПЛАТА / ГАРАНТИЯ» (crm_lead._pmk_won_payment) пишет в одну
    строку и всегда оставляет в её ленте итоговую заметку «откуда сдача» —
    даже когда даты не поменялись.
"""
import datetime

import pytz
from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models
from odoo.tools.misc import clean_context

from .work_days import WEEKDAYS, add_work_days

ORDERED = [("yes", "Да"), ("no", "Нет")]
# «Получен частично» — шаг З-5 (pmk_tech, «Материал пришёл»): пришла часть
# заявок на металл заказа. Новое значение в varchar — миграции не нужно.
METAL = [("none", "—"), ("wait", "Ждём"), ("part", "Получен частично"), ("got", "Получен")]
# Контекст (шаг З-15): даты старта и сдачи пишет наш расчёт срока, а не
# человек — флаг «правили руками» не ставится.
AUTO_DATES = "pmk_orders_auto_dates"
# Контекст: оплату и гарантийное письмо пишет окно «Выиграно» и само зовёт
# пересчёт срока (с итоговой заметкой) — write его не повторяет.
NO_REPLAN = "pmk_orders_no_replan"


def date_text(value):
    """«30.10.2026» — как в Excel Антона."""
    return value.strftime("%d.%m.%Y") if value else ""


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
    pmk_date_start = fields.Date(
        "Старт (план)",
        help="Начало отсчёта срока изготовления: день «Выиграно», оплаты, гарантийного "
             "письма или отправки счёта — по условию счёта.")
    pmk_date_due = fields.Date(
        "Сдача (план)", tracking=True,
        help="Считается из срока изготовления счёта: рабочие дни календаря компании, "
             "без выходных и праздников. Поправили или очистили руками — больше сама "
             "не меняется (расчётная дата — в ленте строки).")
    pmk_date_due_manual = fields.Boolean(
        "Сдачу правили руками", copy=False,
        help="Сдачу (план) поставили руками — расчёт срока её не трогает (шаг З-15).")
    pmk_guarantee = fields.Boolean(
        "Гарантийное письмо", tracking=True,
        help="Работу начали по гарантийному письму вместо оплаты: срок считается от "
             "«Старт (план)» — поставьте в него день письма; дата оплаты срок не двигает.")
    pmk_lead_text = fields.Char(
        related="pmk_sale_order_id.pmk_lead_text", string="Срок изготовления")
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

    # ─── Запись: ручная правка сдачи и пересчёт от оплаты (шаг З-15) ────
    @api.model_create_multi
    def create(self, vals_list):
        auto = self.env.context.get(AUTO_DATES)
        if not auto:
            default_due = self.env.context.get("default_pmk_date_due")
            for vals in vals_list:
                if "pmk_date_due_manual" in vals or "pmk_date_due" not in vals:
                    continue
                # Сдачу поставили сами (импорт, «Новое» с другой датой, чем
                # подсказал счёт) или стёрли подсказанную — «правили руками».
                due = vals["pmk_date_due"]
                if due and str(due) != str(default_due or ""):
                    vals["pmk_date_due_manual"] = True
                elif not due and default_due:
                    vals["pmk_date_due_manual"] = True
        rows = super().create(vals_list)
        if not auto:
            # «Новое» из кнопки «Заказ» со счётом: сдача пуста — посчитать
            # или оставить подсказку в ленте («с согласования чертежей»).
            rows.filtered(lambda row: row.pmk_sale_order_id)._pmk_fill_plan_dates()
        return rows

    def write(self, vals):
        if self.env.context.get(AUTO_DATES):
            return super().write(vals)
        cleared = self.browse()
        if "pmk_date_due" in vals and "pmk_date_due_manual" not in vals:
            # Очистка — тоже ручная правка: срок неизвестен, сама не заполняем.
            vals = dict(vals, pmk_date_due_manual=True)
            if not vals["pmk_date_due"]:
                cleared = self.filtered(lambda row: row.pmk_is_order and row.pmk_date_due)
        if self.env.context.get(NO_REPLAN):
            return super().write(vals)
        first_paid = self.browse()
        if vals.get("pmk_paid_date"):
            # Только когда дата оплаты появилась впервые: вторая оплата и
            # исправление даты сдачу не двигают.
            first_paid = self.filtered(lambda row: row.pmk_is_order and not row.pmk_paid_date)
        # Гарантийное письмо: поставили галочку или поправили старт у такой
        # строки — сдача от старта (дня письма). Сдачу правят в той же
        # записи — она ручная, не трогаем (_pmk_replanable).
        new_guarantee = self.browse()
        letter = self.browse()
        if vals.get("pmk_guarantee"):
            new_guarantee = self.filtered(lambda row: row.pmk_is_order and not row.pmk_guarantee)
        if vals.get("pmk_date_start") and vals.get("pmk_guarantee", True):
            letter = self.filtered(lambda row: row.pmk_is_order and row.pmk_guarantee)
        res = super().write(vals)
        if first_paid:
            first_paid._pmk_replan_from_payment()
        for row in new_guarantee | letter:
            day = row.pmk_date_start or fields.Date.context_today(row)
            row._pmk_replan_from_guarantee(day, always_note=row in new_guarantee)
        if cleared:
            cleared._pmk_note_cleared()
        return res

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
    def _pmk_row_name(self, deal, order):
        """Название строки (шаг З-15): что делаем, а не тема письма.

        «Предмет КП» расчёта счёта → изделия расчёта («Профиль … +1») → имя
        сделки → номер счёта. Расчёт — тот, из которого счёт; у счёта его
        нет или счёта нет — расчёт сделки (по которому счёт выставили бы).
        Имя изделия — целиком: режут только виды.
        """
        order = (order or self.env["sale.order"]).sudo()
        deal = (deal or self.env["crm.lead"]).sudo()
        spec = order.pmk_spec_id.sudo()
        if not spec and deal:
            spec = deal._pmk_invoice_source_spec().sudo()
        note = " ".join((spec.note or "").split()) if spec else ""
        if note:
            return note
        names = [" ".join(name.split()) for name in spec.product_ids.mapped("name")
                 if name and name.strip()] if spec else []
        if names:
            return names[0] if len(names) == 1 else "%s +%s" % (names[0], len(names) - 1)
        return (deal.name or "").strip() or order.name or _("Заказ")

    @api.model
    def _pmk_row_values(self, deal=None, order=None, plan=None):
        """Что знает новая строка: из сделки и счёта (оба могут быть пусты)."""
        order = (order or self.env["sale.order"]).sudo()
        deal = (deal or order.opportunity_id or self.env["crm.lead"]).sudo()
        project = self._pmk_orders_project()
        stage = self._pmk_queue_stage(project)
        partner = (order.partner_id or deal.partner_id).commercial_partner_id
        user = deal.user_id or order.user_id
        vals = {
            "name": self._pmk_row_name(deal, order),
            "project_id": project.id,
            "stage_id": stage.id or False,
            "partner_id": partner.id or False,
            "pmk_deal_id": deal.id or False,
            "pmk_sale_order_id": order.id or False,
            "pmk_metal": "none",
        }
        plan = plan if plan is not None else self._pmk_plan_dates(order)
        if plan["due"]:
            vals.update(pmk_date_start=plan["start"], pmk_date_due=plan["due"],
                        pmk_date_due_manual=False)
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
        order = (order or self.env["sale.order"]).sudo()
        plan = self._pmk_plan_dates(order)
        vals = self._pmk_row_values(deal=deal, order=order, plan=plan)
        # Без чужих default_* (контекст формы сделки или воронки): строка
        # получает только свои значения.
        row = self.sudo().with_context(clean_context(self.env.context)).with_context(
            mail_auto_subscribe_no_notify=True, mail_create_nolog=True,
            default_project_id=vals["project_id"], **{AUTO_DATES: True}).create(vals)
        links = [rec._get_html_link() for rec in (row.pmk_deal_id, row.pmk_sale_order_id) if rec]
        if links:
            row._message_log(body=Markup(_("Заказ в работе появился сам: %s.")) % Markup(", ").join(links))
        if plan["note"]:
            row._message_log(body=escape(plan["note"]))
        return row.with_env(self.env)

    @api.model
    def _pmk_row_defaults(self, deal=None, order=None):
        """Контекст новой строки из кнопки «Заказ» (сделка или счёт)."""
        vals = self._pmk_row_values(deal=deal, order=order)
        vals.pop("pmk_date_due_manual", None)
        for key in ("pmk_date_start", "pmk_date_due"):
            if vals.get(key):
                vals[key] = fields.Date.to_string(vals[key])
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

    # ─── Срок: старт и сдача из условий счёта (шаг З-15) ─────────────────
    @api.model
    def _pmk_work_calendar(self, company, date_from, date_to):
        """Рабочие дни недели и праздники между датами — календарь рабочего
        времени компании (его «Общие выходные»). Без календаря — пн–пт без
        праздников."""
        company = (company or self.env.company).sudo()
        calendar = company.resource_calendar_id.sudo()
        if not calendar:
            return WEEKDAYS, frozenset()
        attendances = calendar.attendance_ids
        if "display_type" in attendances._fields:
            attendances = attendances.filtered(lambda att: not att.display_type)
        workdays = frozenset(int(att.dayofweek) for att in attendances) or WEEKDAYS
        tz = pytz.timezone(calendar.tz or "UTC")
        start_dt = datetime.datetime.combine(date_from, datetime.time.min) - datetime.timedelta(days=1)
        end_dt = datetime.datetime.combine(date_to, datetime.time.max) + datetime.timedelta(days=1)
        # Как ядро (resource.calendar._leave_intervals_batch): общие
        # выходные — без сотрудника, этого календаря или всех календарей.
        leaves = self.env["resource.calendar.leaves"].sudo().search([
            ("resource_id", "=", False),
            ("time_type", "=", "leave"),
            "|", ("calendar_id", "=", calendar.id),
            "&", ("calendar_id", "=", False), ("company_id", "in", [False, company.id]),
            ("date_from", "<=", end_dt), ("date_to", ">=", start_dt),
        ])
        holidays = set()
        for leave in leaves:
            local_from = pytz.utc.localize(leave.date_from).astimezone(tz)
            local_to = pytz.utc.localize(leave.date_to).astimezone(tz)
            last = local_to.date()
            if local_to.time() == datetime.time.min and last > local_from.date():
                last -= datetime.timedelta(days=1)  # «до полуночи следующего дня»
            day = local_from.date()
            while day <= last:
                holidays.add(day)
                day += datetime.timedelta(days=1)
        return workdays, frozenset(holidays)

    @api.model
    def _pmk_add_work_days(self, start, days, company=None):
        """``start`` + ``days`` рабочих дней календаря компании (start не в счёт)."""
        if not start or days <= 0:
            return False
        window = start + datetime.timedelta(days=days * 2 + 62)
        workdays, holidays = self._pmk_work_calendar(company, start, window)
        return add_work_days(start, days, workdays, holidays) or False

    @api.model
    def _pmk_invoice_day(self, order):
        """День счёта для «с даты счёта»: когда его отправили клиенту
        (pmk_sent_date). Дату счёта (date_order) ядро переписывает при
        подтверждении — то есть в момент «Выиграно». Не отправлялся — день,
        когда счёт завели."""
        moment = order.pmk_sent_date or order.create_date or order.date_order
        return fields.Date.context_today(self, timestamp=moment) if moment else False

    @api.model
    def _pmk_plan_dates(self, order, row=None):
        """Старт, сдача и заметка «откуда дата» для строки счёта ``order``.

        ``row`` — уже заведённая строка: «с момента оплаты» берёт её дату
        оплаты (не при гарантийном письме), иначе её старт; новая строка —
        сегодня, день «Выиграно».
        """
        plan = {"start": False, "due": False, "note": None}
        order = (order or self.env["sale.order"]).sudo()
        if not order:
            return plan
        invoice = order.display_name
        days = order.pmk_lead_days or 0
        if days <= 0:
            plan["note"] = _("В счёте %s не указан срок изготовления — «Сдача (план)» "
                             "поставьте руками.", invoice)
            return plan
        lead = order.pmk_lead_text or ""
        if order.pmk_lead_from == "drawings":
            plan["note"] = _(
                "Срок изготовления по счёту %(invoice)s — «%(lead)s»: дату сдачи поставьте, когда "
                "согласуют чертежи.", invoice=invoice, lead=lead)
            return plan
        won = _("дня «Выиграно»; придёт оплата — пересчитаем от её даты")
        if order.pmk_lead_from == "invoice":
            start, why = self._pmk_invoice_day(order), _("отправки счёта %s", invoice)
        elif row and row.pmk_paid_date and not row.pmk_guarantee:
            start, why = row.pmk_paid_date, _("даты оплаты")
        elif row and row.pmk_guarantee and row.pmk_date_start:
            start, why = row.pmk_date_start, _("гарантийного письма")
        elif row and row.pmk_date_start:
            start, why = row.pmk_date_start, won
        else:
            start, why = fields.Date.context_today(self), won
        due = self._pmk_add_work_days(start, days, order.company_id)
        if not due:
            return plan
        plan.update(start=start, due=due, note=_(
            "Сдача (план) %(due)s: %(lead)s, отсчёт от %(start)s (%(why)s).",
            due=date_text(due), lead=lead, start=date_text(start), why=why))
        return plan

    def _pmk_write_plan(self, plan, prefix=None):
        """Записать старт и сдачу из расчёта срока — без флага «руками» и без
        отметки изменений ядром: заметка сама говорит, что и откуда."""
        for row in self:
            row.sudo().with_context(**{AUTO_DATES: True}, mail_notrack=True).write({
                "pmk_date_start": plan["start"], "pmk_date_due": plan["due"],
                "pmk_date_due_manual": False})
            row._pmk_log_plan(plan, prefix=prefix)

    def _pmk_log_plan(self, plan, prefix=None):
        """Заметка «откуда сдача» в ленту строки — без записи дат."""
        for row in self:
            if plan["note"]:
                body = "%s %s" % (prefix, plan["note"]) if prefix else plan["note"]
                row.sudo()._message_log(body=escape(body))

    def _pmk_has_note(self, text):
        """Такая заметка уже есть в ленте строки (подсказку — один раз)."""
        self.ensure_one()
        needle = str(escape(text))
        messages = self.env["mail.message"].sudo().search([
            ("model", "=", self._name), ("res_id", "=", self.id),
            ("message_type", "=", "notification")])
        return any(text in str(m.body) or needle in str(m.body) for m in messages)

    def _pmk_fill_plan_dates(self):
        """Сдача пуста и руками не правилась — посчитать от счёта строки
        (строка нашлась к счёту, «Новое» из кнопки «Заказ»). Срок не
        считается («с согласования чертежей», срок 0) — подсказка в ленту,
        один раз."""
        for row in self:
            if (not row.pmk_is_order or not row.pmk_sale_order_id or row.pmk_date_due
                    or row.pmk_date_due_manual):
                continue
            plan = row._pmk_plan_dates(row.pmk_sale_order_id, row=row)
            if plan["due"]:
                row._pmk_write_plan(plan)
            elif plan["note"] and not row._pmk_has_note(plan["note"]):
                row._pmk_log_plan(plan)

    def _pmk_note_cleared(self):
        """Сдачу очистили руками: остаётся пустой, в ленте — какой была бы
        расчётная (вернуть — вписать её)."""
        for row in self:
            if not row.pmk_sale_order_id:
                continue
            plan = row._pmk_plan_dates(row.pmk_sale_order_id, row=row)
            if plan["due"]:
                row.sudo()._message_log(body=escape(_(
                    "Сдачу (план) очистили — сама больше не считается. По счёту было бы "
                    "%(due)s; вернуть — впишите её.", due=date_text(plan["due"]))))

    def _pmk_replanable(self):
        """Строки, чью сдачу двигает дата оплаты или гарантийного письма:
        счёт «N раб. дней с момента оплаты», сдачу руками не правили."""
        def payment_term(row):
            order = row.pmk_sale_order_id.sudo()
            return bool(order) and (order.pmk_lead_from or "payment") == "payment" \
                and order.pmk_lead_days > 0
        return self.filtered(lambda row: row.pmk_is_order and not row.pmk_date_due_manual
                             and payment_term(row))

    def _pmk_replan_from_payment(self, always_note=False):
        """Дату оплаты внесли впервые: старт = она, сдача — от неё. По
        гарантийному письму — нет: работа уже идёт от письма.
        ``always_note`` — окно «Выиграно»: итоговая заметка, даже если даты
        не поменялись (оплата в день «Выиграно»)."""
        for row in self._pmk_replanable().filtered(lambda r: not r.pmk_guarantee):
            plan = row._pmk_plan_dates(row.pmk_sale_order_id, row=row)
            if not plan["due"]:
                continue
            prefix = _("Пришла оплата.")
            if (plan["start"], plan["due"]) != (row.pmk_date_start, row.pmk_date_due):
                row._pmk_write_plan(plan, prefix=prefix)
            elif always_note:
                row._pmk_log_plan(plan, prefix=prefix)

    def _pmk_replan_from_guarantee(self, day, always_note=False):
        """Гарантийное письмо от ``day``: старт = день письма, сдача — от него.
        ``always_note`` — галочку только что поставили (окно или строка):
        итоговая заметка, даже если даты не поменялись."""
        for row in self._pmk_replanable():
            before = (row.pmk_date_start, row.pmk_date_due)
            if row.pmk_date_start != day:
                row.sudo().with_context(**{AUTO_DATES: True}, mail_notrack=True).write(
                    {"pmk_date_start": day})
            plan = row._pmk_plan_dates(row.pmk_sale_order_id, row=row)
            if not plan["due"]:
                continue
            prefix = _("Гарантийное письмо.")
            if (plan["start"], plan["due"]) != before:
                row._pmk_write_plan(plan, prefix=prefix)
            elif always_note:
                row._pmk_log_plan(plan, prefix=prefix)
