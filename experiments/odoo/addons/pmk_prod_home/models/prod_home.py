# -*- coding: utf-8 -*-
"""Главная производства (16.10.2026): данные страницы одним вызовом.

Как главная продаж (pmk_sales_home): от имени человека, без sudo; лазер, металл и
техрасчёт — мягко (нет прав — нет блока). Прототип принят Антоном 16.10.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.pmk_sales_home.models.sales_home import MONTHS, WEEKDAYS, WEEKDAYS_SHORT, plural

STAGES = [("queue", "очередь"), ("drawings", "чертежи"), ("metal", "металл"), ("work", "в цеху"),
          ("ready", "отгрузка")]
TODO_LIMIT = 7
DRAWINGS_SOON_DAYS = 2


def tons(kg):
    kg = kg or 0.0
    if kg >= 1000:
        return ("%.1f т" % (kg / 1000)).replace(".", ",")
    return "%d кг" % round(kg)


class PmkProdHome(models.AbstractModel):
    _name = "pmk.prod.home"
    _description = "Главная производства"

    @api.model
    def get_dashboard(self):
        today = fields.Date.context_today(self)
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        hello = "Доброе утро" if now.hour < 12 else ("Добрый день" if now.hour < 18 else "Добрый вечер")
        first = (self.env.user.name or "").split()[0] if self.env.user.name else ""
        data = {
            "hello": "%s, %s" % (hello, first) if first else hello,
            "date": "%s, %d %s" % (WEEKDAYS[today.weekday()], today.day, MONTHS[today.month - 1]),
        }
        data["orders"] = self._orders(today)
        data["laser"] = self._laser()
        data["metal"] = self._metal(today)
        data["calc"] = self._calc()
        data["todo"] = self._todo(today, data)
        data.pop("_tasks", None)
        return data

    # ─── заказы в работе ────────────────────────────────────────────────
    def _orders(self, today):
        Task = self.env["project.task"]
        if "pmk_is_order" not in Task._fields or not Task.has_access("read"):
            return None
        try:
            tasks = Task.search([("pmk_is_order", "=", True), ("stage_id.pmk_order_stage", "!=", "shipped")])
            shipped_week = Task.search_count([("pmk_is_order", "=", True), ("pmk_ship_date", ">=", today - timedelta(days=7))])
        except AccessError:
            return None
        code = lambda t: t.stage_id.pmk_order_stage  # noqa: E731
        stages = []
        for key, label in STAGES:
            mine = tasks.filtered(lambda t, k=key: code(t) == k)
            stages.append({"code": key, "label": label, "count": len(mine),
                           "overdue": len(mine.filtered("pmk_overdue"))})
        by = {s["code"]: s for s in stages}
        drawings = tasks.filtered(lambda t: code(t) == "drawings")
        hot = drawings.filtered(lambda t: t.pmk_date_due and t.pmk_date_due <= today + timedelta(days=DRAWINGS_SOON_DAYS))
        work = tasks.filtered(lambda t: code(t) == "work")
        week = []
        for offset in range(7):
            day = today + timedelta(days=offset)
            due = tasks.filtered(lambda t, d=day: t.pmk_date_due == d and code(t) != "pause")
            week.append({"label": "%s %d" % (WEEKDAYS_SHORT[day.weekday()], day.day), "today": offset == 0,
                         "items": [{"id": t.id, "name": self._short(t)} for t in due[:4]],
                         "more": max(0, len(due) - 4)})
        ready_week = tasks.filtered(lambda t: code(t) == "ready" and t.pmk_date_due
                                    and today <= t.pmk_date_due <= today + timedelta(days=6))
        return {
            "total": len(tasks), "overdue": len(tasks.filtered("pmk_overdue")),
            "stages": stages, "pause": len(tasks.filtered(lambda t: code(t) == "pause")),
            "shipped_week": shipped_week,
            "drawings": by["drawings"]["count"], "drawings_hot": len(hot),
            "metal": by["metal"]["count"], "work": by["work"]["count"],
            "work_weight": tons(sum(self._weight(t) for t in work)) if any(self._weight(t) for t in work) else "",
            "hot_word": plural(len(hot), "горит", "горят", "горят"),
            "ready": by["ready"]["count"], "ready_week": len(ready_week),
            "week": week,
            "_hot": hot.ids,
        }

    def _weight(self, task):
        order = task.pmk_sale_order_id if "pmk_sale_order_id" in task._fields else False
        if order and "pmk_ms_weight" in order._fields and order.pmk_ms_weight:
            return order.pmk_ms_weight
        return 0.0

    def _short(self, task):
        name = (task.pmk_sale_order_id.name if task.pmk_sale_order_id else "") or task.name or ""
        return name if len(name) <= 22 else name[:20].rstrip() + "…"

    # ─── лазер ──────────────────────────────────────────────────────────
    def _laser(self):
        Task = self.env["pmk.laser.task"]
        if not Task.has_access("read"):
            return None
        try:
            tasks = Task.search([("state", "!=", "done")], order="date_due asc, id")
        except AccessError:
            return None
        left_sheets = sum(max(0, (t.sheets_total or 0) - (t.sheets_cut or 0)) for t in tasks)
        left_kg = sum(max(0.0, (t.mass_kg or 0.0) - (t.mass_cut_kg or 0.0)) for t in tasks)
        rows = []
        for t in tasks[:5]:
            title = t.partner_id.name or t.note or t.name
            if t.state == "new":
                state = "не разложено"
            elif t.sheets_total:
                state = "%d из %d л. · %d %%" % (t.sheets_cut, t.sheets_total, round(t.progress_pct or 0))
            else:
                state = dict(t._fields["state"].selection).get(t.state, "")
            rows.append({"id": t.id, "name": "%s · %s" % (t.name, title) if title != t.name else t.name,
                         "state": state, "pct": round(t.progress_pct or 0) if t.sheets_total else None})
        return {"count": len(tasks), "sheets": left_sheets, "weight": tons(left_kg), "rows": rows,
                "count_word": plural(len(tasks), "задание", "задания", "заданий"),
                "new": len(tasks.filtered(lambda t: t.state == "new")),
                "_new": tasks.filtered(lambda t: t.state == "new")[:3].ids}

    # ─── металл ─────────────────────────────────────────────────────────
    def _metal(self, today):
        try:
            action = self.env["ir.actions.act_window"]._for_xml_id("pmk_tech.action_metal_requests")
        except (ValueError, AccessError):
            return None
        PO = self.env["purchase.order"]
        if not PO.has_access("read"):
            return None
        domain = self._eval_domain(action.get("domain")) + [
            ("pmk_metal_date", "=", False), ("state", "!=", "cancel")]
        try:
            orders = PO.search(domain, order="date_planned asc, id")
        except AccessError:
            return None
        rows = []
        for po in orders[:5]:
            planned = fields.Date.context_today(self, po.date_planned) if po.date_planned else None
            late = bool(planned and planned < today)
            rows.append({"id": po.id, "name": "%s · %s" % (po.name, po.partner_id.name or ""),
                         "when": ("ждали %s" if late else "придёт %s") % planned.strftime("%d.%m") if planned else "без даты",
                         "late": late})
        late_all = orders.filtered(lambda po: po.date_planned and
                                   fields.Date.context_today(self, po.date_planned) < today)
        return {"count": len(orders), "late": len(late_all), "rows": rows, "_late": late_all[:2].ids,
                "count_word": plural(len(orders), "заявка", "заявки", "заявок")}

    def _eval_domain(self, domain):
        if not domain:
            return []
        if isinstance(domain, str):
            from odoo.tools.safe_eval import safe_eval
            return safe_eval(domain, {"uid": self.env.uid, "context_today": fields.Date.context_today})
        return list(domain)

    # ─── калькуляторы ───────────────────────────────────────────────────
    def _calc(self):
        out = {}
        for key, model, domain in (
                ("dobor", "pmk.dobor.order", [("state", "=", "draft")]),
                ("vent", "pmk.vent.hood.order", [("state", "=", "draft")]),
                ("tech", "pmk.metal.spec", [("pmk_kind", "=", "tech")])):
            if model not in self.env or not self.env[model].has_access("read"):
                out[key] = None
                continue
            Model = self.env[model]
            if any(f not in Model._fields for f, *_ in domain):
                out[key] = None
                continue
            out[key] = Model.search_count(domain)
        return out

    # ─── «Сделать сегодня» ──────────────────────────────────────────────
    def _todo(self, today, data):
        items = []
        orders = data.get("orders") or {}
        Task = self.env["project.task"]
        for task in Task.browse(orders.get("_hot") or []).sorted(lambda t: t.pmk_date_due):
            late = task.pmk_date_due < today
            items.append({"kind": "order", "id": task.id, "level": "danger" if late else "warning",
                          "tag": ("срок %s" % task.pmk_date_due.strftime("%d.%m")),
                          "title": _("Разработать чертежи"), "name": self._short(task),
                          "sub": " · ".join(p for p in (task.partner_id.name, _("стадия «Чертежи»")) if p)})
        metal = data.get("metal") or {}
        for po in self.env["purchase.order"].browse(metal.get("_late") or []):
            items.append({"kind": "metal", "id": po.id, "level": "warning", "tag": _("металл не пришёл"),
                          "title": _("Заявка на металл"), "name": po.name,
                          "sub": "%s · ждали %s" % (po.partner_id.name or "",
                                                     fields.Date.context_today(self, po.date_planned).strftime("%d.%m"))})
        Spec = self.env["pmk.metal.spec"]
        if "layout_stale" in Spec._fields and Spec.has_access("read"):
            # «Раскладка устарела» — вычисляемое без поиска: среди недавно правленных.
            recent = Spec.search([], order="write_date desc", limit=60)
            for spec in recent.filtered("layout_stale")[:2]:
                items.append({"kind": "spec", "id": spec.id, "level": "warning", "tag": _("раскладка устарела"),
                              "title": _("Переразложить листы"), "name": spec.name,
                              "sub": _("детали изменились после раскладки")})
        tasks = self._orders_without_tech()
        for task in tasks[:2]:
            order = task.pmk_sale_order_id
            items.append({"kind": "order", "id": task.id, "level": "warning", "tag": _("нет тех. расчёта"),
                          "title": _("Технический расчёт к счёту"), "name": order.name,
                          "sub": order.partner_id.name or ""})
        laser = data.get("laser") or {}
        for lt in self.env["pmk.laser.task"].browse(laser.get("_new") or []):
            items.append({"kind": "laser", "id": lt.id, "level": "neutral", "tag": _("не разложено"),
                          "title": _("Разложить задание лазеру"), "name": lt.name,
                          "sub": lt.partner_id.name or lt.note or ""})
        for block in ("orders", "metal", "laser"):
            for key in ("_hot", "_late", "_new"):
                (data.get(block) or {}).pop(key, None)
        return items[:TODO_LIMIT]

    def _orders_without_tech(self):
        Task = self.env["project.task"]
        Order = self.env["sale.order"]
        if "pmk_tech_spec_ids" not in Order._fields or "pmk_is_order" not in Task._fields:
            return Task.browse()
        try:
            tasks = Task.search([("pmk_is_order", "=", True),
                                 ("stage_id.pmk_order_stage", "in", ("queue", "drawings", "metal")),
                                 ("pmk_sale_order_id", "!=", False),
                                 ("pmk_sale_order_id.pmk_tech_spec_ids", "=", False)], limit=5)
        except AccessError:
            return Task.browse()
        return tasks

    # ─── переходы ───────────────────────────────────────────────────────
    @api.model
    def open_block(self, key, res_id=False):
        orders = "pmk_orders.action_orders"
        form = lambda model: {"type": "ir.actions.act_window", "res_model": model, "res_id": res_id,  # noqa: E731
                              "views": [[False, "form"]], "target": "current"}
        if key == "orders":
            return self._action(orders)
        if key == "overdue":
            return self._action(orders, domain=[("pmk_overdue", "=", True)], name=_("Просроченные заказы"))
        if key == "stage" and isinstance(res_id, str):
            return self._action(orders, domain=[("stage_id.pmk_order_stage", "=", res_id)])
        if key == "order" and res_id:
            return form("project.task")
        if key == "laser":
            return self._action("pmk_laser.action_laser_task")
        if key == "laser_task" and res_id:
            return form("pmk.laser.task")
        if key == "metal":
            return self._action("pmk_tech.action_metal_requests")
        if key == "metal_po" and res_id:
            return form("purchase.order")
        if key == "spec" and res_id:
            return form("pmk.metal.spec")
        if key == "calc_dobor":
            return self._action("pmk_calc.action_dobor_order", domain=[("state", "=", "draft")])
        if key == "calc_vent":
            return self._action("pmk_calc.action_vent_hood", domain=[("state", "=", "draft")])
        if key == "calc_tech":
            return self._action("pmk_calc.action_metal_spec", domain=[("pmk_kind", "=", "tech")],
                                name=_("Технические расчёты"))
        if key in ("new_spec", "new_dobor", "new_vent", "new_butik"):
            xmlid = {"new_spec": "pmk_calc.action_metal_spec", "new_dobor": "pmk_calc.action_dobor_order",
                     "new_vent": "pmk_calc.action_vent_hood", "new_butik": "pmk_butik.action_butik_spec"}[key]
            action = self._action(xmlid)
            if action:
                by_type = {t: v for v, t in action.get("views") or []}
                action.update(views=[[by_type.get("form", False), "form"]], target="current", res_id=False)
            return action
        return False

    def _action(self, xmlid, domain=None, name=None):
        try:
            action = dict(self.env["ir.actions.act_window"]._for_xml_id(xmlid))
        except (ValueError, AccessError):
            return False
        if domain is not None:
            action["domain"] = domain
        if name:
            action["name"] = name
        return action
