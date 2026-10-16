# -*- coding: utf-8 -*-
"""Главная продаж (16.10.2026): данные страницы одним вызовом.

Всё ищется от имени человека, без sudo: каждый видит то, что ему разрешено
(почта — свои ящики, поступления — у кого есть доступ к банку). Модуля или
прав нет — блок не приходит, страница рисует остальные.
"""
from datetime import datetime, time, timedelta, timezone

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
MONTHS_NOM = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
              "сентябрь", "октябрь", "ноябрь", "декабрь")
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
KP_WAIT_DAYS = 3
MAIL_DAYS = 7
TODO_LIMIT = 6


def money(value):
    """24 700 000 → «24,7 млн ₽», 380 000 → «380 тыс. ₽»."""
    value = value or 0.0
    if abs(value) >= 1e6:
        return ("%.1f млн ₽" % (value / 1e6)).replace(".", ",")
    if abs(value) >= 1e3:
        return "%d тыс. ₽" % round(value / 1e3)
    return "%d ₽" % round(value)


def short_money(value):
    """Для воронки: «4,2 млн», «380 тыс.»."""
    return money(value).replace(" ₽", "")


def day_label(day, today):
    if day == today:
        return "сегодня"
    if day == today - timedelta(days=1):
        return "вчера"
    return "%d %s" % (day.day, MONTHS[day.month - 1][:3] + ".")


class PmkSalesHome(models.AbstractModel):
    _name = "pmk.sales.home"
    _description = "Главная продаж"

    # ─── данные страницы ────────────────────────────────────────────────
    @api.model
    def get_dashboard(self):
        today = fields.Date.context_today(self)
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        hello = "Доброе утро" if now.hour < 12 else ("Добрый день" if now.hour < 18 else "Добрый вечер")
        first_name = (self.env.user.name or "").split()[0] if self.env.user.name else ""
        data = {
            "hello": "%s, %s" % (hello, first_name) if first_name else hello,
            "date": "%s, %d %s" % (WEEKDAYS[today.weekday()], today.day, MONTHS[today.month - 1]),
            "month": MONTHS_NOM[today.month - 1],
        }
        data.update(self._deals(today))
        data["mail"] = self._mail(today)
        data["orders"] = self._orders(today)
        data["payments"] = self._payments(today)
        data["todo"] = self._todo(today, data)
        data.pop("_open_ids", None)
        return data

    def _opp_domain(self):
        return [("type", "=", "opportunity"), ("active", "=", True)]

    def _month_start(self, today):
        start = datetime.combine(today.replace(day=1), time.min)
        return fields.Datetime.to_string(start)

    def _deals(self, today):
        Lead = self.env["crm.lead"]
        if not Lead.has_access("read"):
            return {"deals": None}
        stages = self.env["crm.stage"].search([], order="sequence, id")
        opps = Lead.search(self._opp_domain())
        open_opps = opps.filtered(lambda l: not l.stage_id.is_won)
        month_start = self._month_start(today)
        won = Lead.search(self._opp_domain() + [
            ("stage_id.is_won", "=", True), ("date_closed", ">=", month_start)])
        kp_stage = self.env.ref("crm.stage_lead3", raise_if_not_found=False)
        kp = open_opps.filtered(lambda l: kp_stage and l.stage_id == kp_stage)
        kp_old = kp.filtered(lambda l: self._days_in_stage(l, today) > KP_WAIT_DAYS)

        funnel = []
        widest = max([sum(open_opps.filtered(lambda l, s=s: l.stage_id == s).mapped("expected_revenue"))
                      for s in stages if not s.is_won] + [sum(won.mapped("expected_revenue")), 1.0])
        for stage in stages:
            leads = won if stage.is_won else open_opps.filtered(lambda l, s=stage: l.stage_id == s)
            amount = sum(leads.mapped("expected_revenue"))
            funnel.append({
                "id": stage.id, "name": stage.name, "count": len(leads), "amount": short_money(amount),
                "pct": round(100 * amount / widest) if amount else 0, "won": stage.is_won,
            })

        # Доля выигранных среди закрытых за 30 дней (проигранные — в архиве с вероятностью 0).
        since = fields.Datetime.to_string(datetime.combine(today - timedelta(days=30), time.min))
        won30 = Lead.search_count(self._opp_domain() + [("stage_id.is_won", "=", True), ("date_closed", ">=", since)])
        lost30 = Lead.with_context(active_test=False).search_count([
            ("type", "=", "opportunity"), ("active", "=", False), ("probability", "=", 0),
            ("date_closed", ">=", since)])
        conversion = round(100 * won30 / (won30 + lost30)) if won30 + lost30 else None

        won_amount = sum(won.mapped("expected_revenue"))
        margin = self._weighted_margin(won)
        leads_count = Lead.search_count([("type", "=", "lead"), ("active", "=", True)])
        day_start = fields.Datetime.to_string(self._local_midnight(today))
        leads_today = Lead.search_count([("type", "=", "lead"), ("active", "=", True),
                                         ("create_date", ">=", day_start)])

        managers = {}
        for lead in open_opps:
            row = managers.setdefault(lead.user_id.id or 0, self._manager_row(lead.user_id))
            row["open"] += 1
            row["open_sum"] += lead.expected_revenue or 0.0
        for lead in won:
            row = managers.setdefault(lead.user_id.id or 0, self._manager_row(lead.user_id))
            row["won"] += 1
            row["won_sum"] += lead.expected_revenue or 0.0
        rows = sorted(managers.values(), key=lambda r: -(r["open_sum"] + r["won_sum"]))
        for row in rows:
            row["open_text"] = "%d · %s" % (row["open"], short_money(row["open_sum"])) if row["open"] else "—"
            row["won_text"] = "%d · %s" % (row["won"], short_money(row["won_sum"])) if row["won"] else "—"

        return {
            "deals": {
                "open": len(open_opps), "open_sum": money(sum(open_opps.mapped("expected_revenue"))),
                "kp": len(kp), "kp_old": len(kp_old),
                "won": len(won), "won_sum": money(won_amount),
                "won_margin": ("маржа %d %%" % round(margin)) if margin is not None else "",
                "leads": leads_count, "leads_today": leads_today,
                "kp_stage_id": kp_stage.id if kp_stage else False,
            },
            "funnel": funnel,
            "conversion": conversion,
            "managers": rows,
            "_open_ids": open_opps.ids,
        }

    def _manager_row(self, user):
        return {"id": user.id or 0, "name": user.name or _("Без ответственного"),
                "open": 0, "open_sum": 0.0, "won": 0, "won_sum": 0.0}

    def _weighted_margin(self, leads):
        """Маржа выигранного: средняя по расчётам, взвешенная ценой клиенту."""
        total = weighted = 0.0
        for lead in leads:
            spec = lead.pmk_spec_id if "pmk_spec_id" in lead._fields else False
            price = spec.price_customer_total if spec else 0.0
            if price:
                total += price
                weighted += price * (spec.margin_pct or 0.0)
        return weighted / total if total else None

    def _days_in_stage(self, lead, today):
        moved = lead.date_last_stage_update or lead.create_date
        return (today - fields.Date.context_today(self, moved)).days if moved else 0

    def _local_midnight(self, day):
        """Полночь дня по часовому поясу человека → UTC для поиска по Datetime."""
        tz_now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        local = tz_now.replace(year=day.year, month=day.month, day=day.day, hour=0, minute=0,
                               second=0, microsecond=0)
        return local.astimezone(timezone.utc).replace(tzinfo=None) if local.tzinfo else local

    def _mail(self, today):
        if "mail.client.message" not in self.env:
            return None
        Message = self.env["mail.client.message"]
        if not Message.has_access("read"):
            return None
        since = fields.Datetime.to_string(datetime.combine(today - timedelta(days=MAIL_DAYS), time.min))
        inbox = [("folder_id.role", "=", "inbox"), ("is_spam", "=", False), ("date", ">=", since)]
        unread = inbox + [("flag_seen", "=", False)]
        no_lead = inbox + [("pmk_lead_id", "=", False)]
        try:
            latest = Message.search(no_lead, order="date desc", limit=5)
            items = [{
                "id": msg.id,
                "who": msg.partner_id.name or (msg.email_from or "").split("<")[0].strip(' "') or msg.email_from,
                "subject": msg.subject or _("(без темы)"),
                "when": self._mail_when(msg.date, today),
            } for msg in latest]
            return {
                "unread": Message.search_count(unread),
                "unread_no_lead": Message.search_count(unread + [("pmk_lead_id", "=", False)]),
                "no_lead": Message.search_count(no_lead),
                "items": items,
            }
        except AccessError:
            return None

    def _mail_when(self, value, today):
        if not value:
            return ""
        local = fields.Datetime.context_timestamp(self, value)
        if local.date() == today:
            return "сегодня %s" % local.strftime("%H:%M")
        return day_label(local.date(), today)

    def _orders(self, today):
        Task = self.env["project.task"]
        if "pmk_is_order" not in Task._fields or not Task.has_access("read"):
            return None
        try:
            tasks = Task.search([("pmk_is_order", "=", True), ("stage_id.pmk_order_stage", "!=", "shipped")])
        except AccessError:
            return None
        codes = [("metal", "ждём металл"), ("drawings", "чертежи"), ("work", "в работе"),
                 ("ready", "к отгрузке")]
        stages = [{"code": code, "label": label,
                   "count": len(tasks.filtered(lambda t, c=code: t.stage_id.pmk_order_stage == c))}
                  for code, label in codes]
        # Просрочка: сколько всего и последняя (самая свежая) — старые хвосты не
        # заслоняют то, что горит сейчас.
        overdue = tasks.filtered(lambda t: t.pmk_overdue).sorted(lambda t: t.pmk_date_due, reverse=True)
        last = overdue[:1]
        name = last.pmk_sale_order_id.name or last.name or ""
        return {
            "total": len(tasks),
            "stages": stages,
            "overdue": len(overdue),
            "burning": {
                "id": last.id, "name": name if len(name) <= 48 else name[:46].rstrip() + "…",
                "due": last.pmk_date_due.strftime("%d.%m"),
            } if last else None,
        }

    def _payments(self, today):
        if "pmk.bank.payment" not in self.env:
            return None
        Payment = self.env["pmk.bank.payment"]
        if not Payment.has_access("read"):
            return None
        start = today - timedelta(days=6)
        try:
            pays = Payment.search([("executed", ">=", start), ("executed", "<=", today), ("amount", ">", 0)])
        except AccessError:
            return None
        days = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            amount = sum(pays.filtered(lambda p, d=day: p.executed == d).mapped("amount"))
            days.append({"label": WEEKDAYS_SHORT[day.weekday()], "amount": amount, "text": money(amount)})
        top = max([d["amount"] for d in days] + [1.0])
        for d in days:
            d["pct"] = round(100 * d["amount"] / top) if d["amount"] else 0
        return {"total": money(sum(pays.mapped("amount"))), "count": len(pays), "days": days}

    def _todo(self, today, data):
        """«Сделать сегодня»: просрочено → маржа в минус → без цены → КП молчит → почта."""
        items = []
        Lead = self.env["crm.lead"]
        open_opps = Lead.browse(data.get("_open_ids") or [])
        kp_stage_id = (data.get("deals") or {}).get("kp_stage_id")
        for lead in open_opps.filtered(lambda l: l.date_deadline and l.date_deadline < today) \
                .sorted(lambda l: l.date_deadline):
            items.append(self._todo_item(lead, "danger", "просрочено", _("Ответить клиенту"),
                                         _("срок был %s") % lead.date_deadline.strftime("%d.%m")))
        if "pmk_chip_margin_bad" in Lead._fields:
            for lead in open_opps.filtered("pmk_chip_margin_bad"):
                items.append(self._todo_item(lead, "danger", lead.pmk_chip_margin or _("маржа в минус"),
                                             _("Пересмотреть цену КП"), _("цена клиенту ниже затрат")))
        if "pmk_no_price_label" in Lead._fields:
            for lead in open_opps.filtered("pmk_no_price_label"):
                items.append(self._todo_item(lead, "warning", lead.pmk_no_price_label,
                                             _("Дозаполнить цены"), _("в расчёте позиции без цены закупки")))
        for lead in open_opps.filtered(lambda l: kp_stage_id and l.stage_id.id == kp_stage_id):
            days = self._days_in_stage(lead, today)
            if days > KP_WAIT_DAYS:
                items.append(self._todo_item(lead, "warning", "КП %d дн." % days, _("Напомнить о КП"),
                                             _("ответа нет")))
        seen, unique = set(), []
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                unique.append(item)
        unique = unique[:TODO_LIMIT]
        mail = data.get("mail")
        if mail and mail["unread_no_lead"]:
            unique.append({"id": False, "kind": "mail", "level": "neutral",
                           "tag": "%d писем" % mail["unread_no_lead"],
                           "title": _("Разобрать почту без лида"), "name": "",
                           "sub": _("непрочитанные за %d дней — заявки могли прийти от новых клиентов") % MAIL_DAYS})
        return unique

    def _todo_item(self, lead, level, tag, title, why):
        partner = lead.partner_id.commercial_partner_id.name or lead.partner_name or ""
        return {"id": lead.id, "kind": "deal", "level": level, "tag": tag, "title": title,
                "name": lead.name, "sub": " · ".join(p for p in (partner, why) if p)}

    # ─── переходы по щелчку ─────────────────────────────────────────────
    @api.model
    def open_block(self, key, res_id=False):
        """Действие для щелчка по блоку главной. Нет прав или модуля — False."""
        today = fields.Date.context_today(self)
        pipeline = "crm.crm_lead_action_pipeline"
        if key == "deal" and res_id:
            return {"type": "ir.actions.act_window", "res_model": "crm.lead", "res_id": res_id,
                    "views": [[False, "form"]], "target": "current"}
        if key == "deals":
            return self._action(pipeline)
        if key == "stage" and res_id:
            stage = self.env["crm.stage"].browse(res_id)
            domain = [("stage_id", "=", stage.id)]
            if stage.is_won:
                domain.append(("date_closed", ">=", self._month_start(today)))
            return self._action(pipeline, domain=domain, name=stage.name, views=["list", "kanban", "form"])
        if key == "kp":
            stage = self.env.ref("crm.stage_lead3", raise_if_not_found=False)
            return self._action(pipeline, domain=[("stage_id", "=", stage.id if stage else 0)],
                                name=_("КП ждут ответа"), views=["list", "kanban", "form"])
        if key == "won":
            return self._action(pipeline, domain=[("stage_id.is_won", "=", True),
                                                  ("date_closed", ">=", self._month_start(today))],
                                name=_("Выиграно в этом месяце"), views=["list", "kanban", "form"])
        if key == "leads":
            return self._action("crm.crm_lead_all_leads")
        if key == "analytics":
            return self._action("pmk_deal.action_pipeline_analytics")
        if key == "mail":
            return self._action("pmk_mail_ui.action_mail_sale")
        if key == "letter" and res_id and "pmk.flow.builder" in self.env:
            msg = self.env["mail.client.message"].browse(res_id).exists()
            if msg:
                return self.env["pmk.flow.builder"]._letter_action(msg) or self._action("pmk_mail_ui.action_mail_sale")
        if key == "orders":
            return self._action("pmk_orders.action_orders")
        if key == "order_stage" and isinstance(res_id, str):
            return self._action("pmk_orders.action_orders",
                                domain=[("stage_id.pmk_order_stage", "=", res_id)])
        if key == "overdue":
            return self._action("pmk_orders.action_orders", domain=[("pmk_overdue", "=", True)],
                                name=_("Просроченные заказы"))
        if key == "order" and res_id:
            return {"type": "ir.actions.act_window", "res_model": "project.task", "res_id": res_id,
                    "views": [[False, "form"]], "target": "current"}
        if key == "payments":
            return self._action("pmk_bank.action_pmk_bank_payment")
        return False

    def _action(self, xmlid, domain=None, name=None, views=None):
        try:
            action = dict(self.env["ir.actions.act_window"]._for_xml_id(xmlid))
        except (ValueError, AccessError):
            try:
                action = dict(self.env["ir.actions.actions"]._for_xml_id(xmlid))
            except (ValueError, AccessError):
                return False
        if domain is not None:
            action["domain"] = domain
        if name:
            action["name"] = name
        if views:
            by_type = {view_type: view_id for view_id, view_type in action.get("views") or []}
            action["views"] = [[by_type.get(v, False), v] for v in views]
        return action
