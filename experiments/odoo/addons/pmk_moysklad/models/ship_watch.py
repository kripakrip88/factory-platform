# -*- coding: utf-8 -*-
"""«Оплачено, а отгрузки нет» — Телеграм Владиславу Чулкову (Антон 21.10.2026).

Сделку закрывает документ «Отгрузка» МоегоСклада (deal_link.py). Если заказ
отгрузили, а отгрузку провести забыли, сделка висит в «Оплачено / в работе»,
а деньги и УПД расходятся. Каждый день в 9:00 по Хабаровску — сводка тех
оплаченных счетов (оплачен / предоплата / постоплата), что не отгружены на
всю сумму, когда со дня оплаты прошло:
- срок изготовления счёта в рабочих днях + SHIP_SPARE_DAYS («запас 5 дней»);
- без срока — SHIP_NO_TERM_DAYS (Антон: «лучше 10 дней»).

День оплаты — когда синхронизация впервые увидела оплаченный статус
(pmk_ms_paid_on); у счетов до выкладки — дата счёта. Только счета от
SHIP_FROM (Антон: «только с 10 октября 2026 года»). Про один счёт — один раз
(pmk_ms_ship_notified); по понедельникам — полный список того, что висит.

Получатель — системный параметр pmk_moysklad.ship_notify_user_id, пусто —
пользователь «Владислав Чулков». Нет такого или не привязан Телеграм — молчит.
"""
import html
import logging
from datetime import date, datetime, timedelta

from odoo import _, api, fields, models

from .deal_link import PAID_STATES

_logger = logging.getLogger(__name__)

SHIP_FROM = date(2026, 10, 10)
SHIP_SPARE_DAYS = 5
SHIP_NO_TERM_DAYS = 10
KHV = timedelta(hours=10)  # Хабаровск, UTC+10


def add_workdays(start, days):
    """start + days рабочих дней (пн–пт; праздники не считаем)."""
    day, left = start, days
    while left > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return day


class SaleOrderShipWatch(models.Model):
    _inherit = "sale.order"

    pmk_ms_paid_on = fields.Date(
        "Оплачен (по МоемуСкладу)", copy=False, readonly=True,
        help="День, когда синхронизация впервые увидела счёт оплаченным "
             "(Оплачен / Предоплата получена / Постоплата).")
    pmk_ms_ship_notified = fields.Date(
        "Напомнили об отгрузке", copy=False, readonly=True,
        help="Когда Телеграм сказал «оплачено, а отгрузки нет» — второй раз про этот счёт не пишет.")

    def _pmk_ship_due(self):
        """День, после которого отсутствие отгрузки — повод напомнить."""
        self.ensure_one()
        if not self.pmk_ms_paid_on:
            return None
        if self.pmk_lead_days:
            return add_workdays(self.pmk_ms_paid_on, self.pmk_lead_days) + timedelta(days=SHIP_SPARE_DAYS)
        return self.pmk_ms_paid_on + timedelta(days=SHIP_NO_TERM_DAYS)

    @api.model
    def _pmk_ship_pending(self, today):
        """Оплаченные счета от SHIP_FROM, не отгруженные на всю сумму, у которых срок вышел."""
        orders = self.search([
            ("pmk_ms_id", "!=", False), ("pmk_ms_state", "in", list(PAID_STATES)),
            ("pmk_ms_paid_on", "!=", False),
            # Полночь 10.10 по Хабаровску — в UTC, как хранит Odoo.
            ("date_order", ">=", datetime.combine(SHIP_FROM, datetime.min.time()) - KHV)])
        out = self.browse()
        for order in orders:
            total = order.pmk_ms_sum or order.amount_total
            if total > 0 and (order.pmk_ms_shipped_sum or 0.0) >= total - 0.01:
                continue
            due = order._pmk_ship_due()
            if due and due < today:
                out |= order
        return out.sorted(lambda o: (o.pmk_ms_paid_on, o.name or ""))


class PmkMoyskladShipWatch(models.AbstractModel):
    _inherit = "pmk.moysklad"

    @api.model
    def _ms_deal_after_upsert(self, order, inv):
        """День оплаты — первый раз, когда синхронизация видит оплаченный статус."""
        if order.pmk_ms_state in PAID_STATES and not order.pmk_ms_paid_on:
            order.sudo().pmk_ms_paid_on = (fields.Datetime.now() + KHV).date()
        return super()._ms_deal_after_upsert(order, inv)

    @api.model
    def _pmk_ship_recipient(self):
        Users = self.env["res.users"].sudo()
        uid = self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.ship_notify_user_id")
        if uid and uid.isdigit():
            return Users.browse(int(uid)).exists()
        found = Users.search([("name", "ilike", "Чулков"), ("name", "ilike", "Владислав")], limit=2)
        return found if len(found) == 1 else Users

    @api.model
    def _cron_ship_watch(self):
        """Ежедневная сводка (крон в 9:00 по Хабаровску)."""
        if "pmk.telegram.bot" not in self.env:
            return False
        user = self._pmk_ship_recipient()
        if not user or not user.pmk_telegram_id:
            return False
        today = (fields.Datetime.now() + KHV).date()
        pending = self.env["sale.order"].sudo()._pmk_ship_pending(today)
        fresh = pending.filtered(lambda o: not o.pmk_ms_ship_notified)
        monday = today.weekday() == 0
        shown = pending if monday else fresh
        if not shown:
            return True
        text = self._pmk_ship_text(shown, pending, today, full=monday)
        if self.env["pmk.telegram.bot"].sudo().pmk_send_user(user, text):
            fresh.write({"pmk_ms_ship_notified": today})
            return True
        _logger.warning("pmk_moysklad: сводка «нет отгрузки» не ушла пользователю %s", user.login)
        return False

    @api.model
    def _pmk_ship_text(self, shown, pending, today, full=False):
        def money(value):
            return ("{:,.0f}".format(value or 0)).replace(",", " ") + " ₽"
        head = (_("📦 Оплачено, а отгрузки в МоёмСкладе нет — всё, что висит (%s)", len(shown)) if full
                else _("📦 Оплачено, а отгрузки в МоёмСкладе нет — %s нов.", len(shown)))
        lines = ["<b>%s</b>" % html.escape(head)]
        for order in shown[:40]:
            state = "постоплата с" if order.pmk_ms_state == "Постоплата" else "оплачен"
            term = (_("срок %s раб. дн.", order.pmk_lead_days) if order.pmk_lead_days
                    else _("срок не указан"))
            late = (today - order._pmk_ship_due()).days
            link = order.pmk_ms_url
            name = html.escape(order.name or "")
            lines.append("• %s · %s · %s · %s %s, %s — <b>просрочено %s дн.</b>" % (
                '<a href="%s">Счёт %s</a>' % (html.escape(link), name) if link else _("Счёт %s", name),
                html.escape(order.partner_id.commercial_partner_id.name or ""),
                money(order.pmk_ms_sum or order.amount_total),
                state, order.pmk_ms_paid_on.strftime("%d.%m"), html.escape(term), late))
        if len(shown) > 40:
            lines.append(_("…и ещё %s", len(shown) - 40))
        if not full:
            lines.append(_("Всего висит без отгрузки: %s", len(pending)))
        lines.append(html.escape(_("Отгрузили — проведите «Отгрузку» к счёту в МоёмСкладе, и счёт уйдёт из списка.")))
        return "\n".join(lines)
