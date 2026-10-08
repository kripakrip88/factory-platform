# -*- coding: utf-8 -*-
"""«Материал пришёл» — отметка прихода металла без склада (шаг З-5).

Карточка 5 проекта «Заказ от заявки до цеха», решения Антона 07–08.10.2026:
снабженец (Владимир Голубенко) работает в штатном заказе поставщику —
поставщик, «Ожидаемое прибытие», «Подтвердить заказ». Металл пришёл —
кнопка «Материал пришёл»: дата прихода в заказе (своё поле «Материал
пришёл», сегодня; поправить можно в форме), в строке «Заказов в работе» —
«Металл: Получен» и дата «Металл получен».
СЛОВА: в заказе поставщику (кнопка, поле, состояние заявки, заметка) —
«Материал пришёл»: заявка заводит заказы и на крепёж, и на краску; в
планировщике — «Металл: Получен» / «Металл получен» (так в задаче). Склад не ведём: «Поступление», которое ядро
(purchase_stock) заводит при подтверждении, не проводим — кнопка с ним не
связана; спрятать его — карточка 6.

КНОПКА (вид views/metal_arrival_views.xml):
  • подтверждённый заказ — залитая, единственная залитая на экране
    (у штатной «Получить» заливка снята: она открывает «Поступление», а
    его «Подтвердить» проводит приход — ловушка карточки 6);
  • отправленный поставщику — контурная (залитая — штатная «Подтвердить
    заказ»): заказ подтверждается штатным button_confirm, как сделал бы
    снабженец, затем ставится дата. Ушёл «на согласование» (двойное
    утверждение) — дата всё равно ставится: наблюдаем, не держим; заметка
    в ленте и уведомление говорят, что вышло — подтверждён или ушёл на
    согласование;
  • на согласовании — контурная, ставит только дату;
  • черновик и отменённый — кнопки нет: черновик ещё не заказан.
  • «Снять «Материал пришёл»» — для ошибок: стирает дату, заказ остаётся
    подтверждённым, «Поступление» не трогаем.
  • список «Заявки на металл» — та же кнопка для выбранных: подходящие
    отмечаются (отправленные поставщику — сначала подтверждаются, это
    названо в подсказке и в уведомлении), остальные пропускаются, итог —
    уведомлением словами.
  • заказ вернули в черновик («Отменить» → «В черновик», чтобы поправить
    поставщика или количество) — отметка снимается сама, с заметкой в
    ленте: черновик ещё не заказан. Отметка считается только у заказанного
    (ARRIVAL_STATES) — в планировщике, в состоянии заявки и в фильтре.

ПЛАНИРОВЩИК. Строка заказа (pmk_task_id заявки, иначе строка её счёта) —
«Металл» по заявкам на металл строки (_pmk_metal_request_domain: её счёт
или она сама). Считаются заявки не отменённые и с позициями: черновик с
позициями (и на «Поставщик не выбран») — ещё не заказан, значит не пришёл;
опустевший черновик не считается. Пришли все — «Получен», часть —
«Получен частично», ни одна — «Ждём». Ни одной считаемой — поле не трогаем
(строки руками и из импорта Excel). «Металл получен» строки — самая поздняя
дата прихода среди пришедших.
ЭТАП НЕ ДВИГАЕМ (решение «утверждаете вы», принцип «наблюдать, а не
контролировать»): из «Ждём металл» в работу строку переводит планировщик
или директор; признак прихода — «Металл: Получен» и дата в строке, фильтр
«Металл получен». Фильтр «Ждём металл» — кто ещё ждёт: «Металл» «Ждём» /
«Получен частично», а этап «Ждём металл» — только без «Получен».

ПРАЙС НЕ ПОПОЛНЯЕМ. Ядро при подтверждении заводит новому поставщику товара
строку прайса по цене заказа (_add_supplier_to_product). У заявки на металл
это вредно: подтверждённая заявка на «Поставщик не выбран» завела бы строку
с ценой 0 — и расчёт (_pmk_find_seller моста: дешевле — раньше) брал бы её;
цена листа не 1500×6000 ушла бы в прайс как цена листа 1500×6000. Прайс
заявок пополняется только загрузкой прайсов. Прочие закупки — как в ядре.

ЛЕНТА — заметками (_message_log): без писем и подписчиков.
"""
from markupsafe import Markup

from odoo import _, fields, models
from odoo.tools.misc import format_date

from odoo.addons.pmk_calc.models.spec_layout import _plural

from .purchase_order import ARRIVAL_STATES, SKIP_REFRESH


class PurchaseOrderArrival(models.Model):
    _inherit = "purchase.order"

    pmk_metal_date = fields.Date(
        "Материал пришёл", copy=False,
        help="Когда материал пришёл на завод. Ставит кнопка «Материал пришёл» "
             "(сегодня), поправить можно здесь. На склад ничего не проводится; "
             "в «Заказах в работе» у заказа — «Металл: Получен». Заказ вернули "
             "в черновик — дата снимается.")

    # ─── Кнопки ─────────────────────────────────────────────────────────
    def action_pmk_material_arrived(self):
        """«Материал пришёл»: дата прихода — сегодня; отправленный заказ
        сначала подтверждается штатно. «Поступление» не проводится."""
        eligible = self.filtered(
            lambda order: order.state in ARRIVAL_STATES and not order.pmk_metal_date)
        skipped = self - eligible
        if not eligible:
            return self._pmk_arrival_notice(eligible, skipped)
        today = fields.Date.context_today(self)
        quiet = eligible.with_context(**{SKIP_REFRESH: True})
        sent = quiet.filtered(lambda order: order.state == "sent")
        if sent:
            # Как штатная «Подтвердить заказ» (validate_analytic — её контекст).
            sent.with_context(validate_analytic=True).button_confirm()
        quiet.write({"pmk_metal_date": today})
        day = format_date(self.env, today)
        for order in eligible:
            text = _("Материал пришёл %(date)s — на склад не проводили.", date=day)
            if order in sent:
                # Слово — по тому, что вышло: при двойном утверждении
                # button_confirm отправляет заказ на согласование.
                if order.state == "to approve":
                    text += " " + _("Заказ отправлен этой кнопкой на согласование.")
                else:
                    text += " " + _("Заказ подтверждён этой кнопкой.")
            order._message_log(body=Markup("<p>%s</p>") % text)
        eligible._pmk_refresh_planner_metal(arrived=True)
        if len(self) > 1 or skipped:
            return self._pmk_arrival_notice(eligible, skipped, sent=sent)
        return True

    def action_pmk_material_undo(self):
        """«Снять «Материал пришёл»»: дата прихода поставлена по ошибке. Заказ остаётся
        подтверждённым, «Поступление» не трогаем."""
        marked = self.filtered("pmk_metal_date")
        if not marked:
            return True
        days = {order: format_date(self.env, order.pmk_metal_date) for order in marked}
        marked.with_context(**{SKIP_REFRESH: True}).write({"pmk_metal_date": False})
        for order in marked:
            order._message_log(body=Markup("<p>%s</p>") % _(
                "Отметка «Материал пришёл %(date)s» снята.", date=days[order]))
        marked._pmk_refresh_planner_metal(arrived=False)
        return True

    def _pmk_arrival_notice(self, done, skipped, sent=None):
        """Итог кнопки для нескольких заказов (список «Заявки на металл»).
        sent — отправленные поставщику, которые кнопка сначала подтвердила
        (или отправила на согласование): называем их, а не молчим."""
        parts = []
        if done:
            parts.append(_("Отмечено «Материал пришёл»: %s.", ", ".join(done.mapped("name"))))
        if sent:
            approved = sent.filtered(lambda order: order.state == "purchase")
            waiting = sent - approved
            if approved:
                parts.append(_("Подтверждены этой кнопкой: %s.",
                               ", ".join(approved.mapped("name"))))
            if waiting:
                parts.append(_("Отправлены этой кнопкой на согласование: %s.",
                               ", ".join(waiting.mapped("name"))))
        if skipped:
            reasons = []
            already = skipped.filtered("pmk_metal_date")
            drafts = skipped.filtered(lambda o: not o.pmk_metal_date and o.state == "draft")
            cancelled = skipped.filtered(lambda o: not o.pmk_metal_date and o.state == "cancel")
            if already:
                reasons.append(_("уже отмечены — %s", ", ".join(already.mapped("name"))))
            if drafts:
                reasons.append(_("черновики, ещё не заказаны — %s", ", ".join(drafts.mapped("name"))))
            if cancelled:
                reasons.append(_("отменены — %s", ", ".join(cancelled.mapped("name"))))
            parts.append(_("Пропущено: %s.", "; ".join(reasons)))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Материал пришёл"),
                "message": " ".join(parts),
                "type": "success" if done else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    # ─── Планировщик ────────────────────────────────────────────────────
    def _pmk_arrival_tasks(self):
        """Строки «Заказов в работе» заказов: строка заявки (pmk_task_id),
        иначе строка её счёта. Только действующие строки планировщика."""
        Task = self.env["project.task"].sudo()
        tasks = Task.browse()
        for order in self.sudo():
            if order.pmk_task_id:
                tasks |= order.pmk_task_id
            elif order.pmk_sale_order_id:
                tasks |= Task.search([("pmk_sale_order_id", "=", order.pmk_sale_order_id.id)])
        return tasks.filtered(lambda task: task.active and task.project_id.pmk_is_orders)

    def _pmk_refresh_planner_metal(self, arrived=None):
        """«Металл» строк планировщика — по их заявкам. arrived — нажата
        «Материал пришёл» (True) или «Снять «Материал пришёл»» (False):
        заметка в ленте строки; иначе (правка даты, отмена заказа, возврат
        в черновик) — молча."""
        tasks = self._pmk_arrival_tasks()
        if not tasks:
            return tasks
        tasks._pmk_metal_refresh()
        if arrived is not None:
            metal = dict(tasks._fields["pmk_metal"].selection)
            for task in tasks:
                counted = task._pmk_metal_requests()
                mine = self.filtered(lambda order: order in counted)
                if not mine:
                    continue
                what = ", ".join("%s (%s)" % (order.name, order.partner_id.display_name)
                                 for order in mine)
                if arrived:
                    head = _("Материал пришёл по заявке %(orders)s, %(date)s",
                             orders=what, date=format_date(self.env, max(mine.mapped("pmk_metal_date"))))
                else:
                    head = _("Отметка «Материал пришёл» снята: %s", what)
                got = counted._pmk_arrived()
                tail = _("Металл — %(state)s (%(got)s из %(all)s %(word)s)",
                         state=metal.get(task.pmk_metal, "—").lower(),
                         got=len(got), all=len(counted),
                         word=_plural(len(counted), "заявки", "заявок", "заявок"))
                task._message_log(body=Markup("<p>%s. %s.</p>") % (head, tail))
        return tasks

    def _pmk_arrived(self):
        """Заказы с отметкой прихода, которые уже заказаны (ARRIVAL_STATES):
        у черновика и отменённого отметка не считается."""
        return self.filtered(
            lambda order: order.pmk_metal_date and order.state in ARRIVAL_STATES)

    # ─── Запись ─────────────────────────────────────────────────────────
    def write(self, vals):
        """Дату поправили руками, заказ отменили, вернули в черновик, черновик
        опустел — «Металл» строки планировщика пересчитывается.

        Вернули в черновик (штатная «В черновик» после «Отменить» — чтобы
        поправить поставщика или количество) — отметка «Материал пришёл»
        снимается с заметкой в ленте: черновик ещё не заказан, а после
        повторного подтверждения старая дата выглядела бы отметкой, которой
        никто не ставил."""
        stale = {}
        if vals.get("state") == "draft" and "pmk_metal_date" not in vals:
            stale = {order: format_date(self.env, order.pmk_metal_date)
                     for order in self.filtered("pmk_metal_date")}
            if stale:
                vals = dict(vals, pmk_metal_date=False)
        watch = (not self.env.context.get(SKIP_REFRESH)
                 and {"pmk_metal_date", "state", "order_line"} & set(vals))
        res = super().write(vals)
        for order, day in stale.items():
            order._message_log(body=Markup("<p>%s</p>") % _(
                "Заказ вернули в черновик — отметка «Материал пришёл %(date)s» снята: "
                "черновик ещё не заказан.", date=day))
        if watch:
            linked = self.filtered(lambda order: order.pmk_task_id or order.pmk_sale_order_id)
            if linked:
                linked._pmk_refresh_planner_metal()
        return res

    def unlink(self):
        tasks = self._pmk_arrival_tasks()
        res = super().unlink()
        tasks.exists()._pmk_metal_refresh()
        return res

    def _add_supplier_to_product(self):
        """Заявке на металл прайс не пополняем (см. описание модуля)."""
        return super(PurchaseOrderArrival, self.filtered(
            lambda order: not order.pmk_tech_spec_id))._add_supplier_to_product()


class ProjectTaskArrival(models.Model):
    _inherit = "project.task"

    pmk_metal_date = fields.Date(
        "Металл получен", copy=False,
        help="Когда пришла последняя заявка на металл этого заказа. Ставит кнопка "
             "«Материал пришёл» в заказе поставщику; строке без заявок — руками.")

    def _pmk_metal_requests(self):
        """Заявки на металл строки, которые считаются: не отменённые и с
        позициями. Черновик с позициями — ещё не заказан (не пришёл)."""
        self.ensure_one()
        orders = self.env["purchase.order"].sudo().search(self._pmk_metal_request_domain())
        return orders.filtered(lambda order: order.state != "cancel" and order.order_line.filtered(
            lambda line: not line.display_type))

    def _pmk_metal_state_from_requests(self):
        """→ (состояние «Металла», дата прихода) по заявкам; заявок нет —
        (None, None): поле не трогаем."""
        self.ensure_one()
        orders = self._pmk_metal_requests()
        if not orders:
            return None, None
        got = orders._pmk_arrived()
        if not got:
            return "wait", False
        return ("got" if got == orders else "part"), max(got.mapped("pmk_metal_date"))

    def _pmk_metal_refresh(self):
        """Записать «Металл» и «Металл получен» по заявкам — только если
        поменялось. Этап не трогаем (решает планировщик)."""
        for task in self:
            state, day = task._pmk_metal_state_from_requests()
            if state is None:
                continue
            vals = {}
            if task.pmk_metal != state:
                vals["pmk_metal"] = state
            if (task.pmk_metal_date or False) != (day or False):
                vals["pmk_metal_date"] = day
            if vals:
                # sudo — у снабженца может не быть «Проектов»; автор истории —
                # тот, кто нажал (sudo пользователя не меняет).
                task.sudo().with_context(mail_auto_subscribe_no_notify=True).write(vals)
        return self
