# -*- coding: utf-8 -*-
"""Главная закупок (18.10.2026): данные страницы одним вызовом.

Как главные продаж и производства: от имени человека, без sudo; нет прав на блок —
нет блока. Прототип показан Антону 18.10: смотрят оба — руководитель и снабженец;
«В пути» оставить; прайсы — маяком «последний от такого-то числа».

Заявка на металл — штатный заказ поставщику с техническим расчётом
(pmk_tech_spec_id). Стадии — как в строке состояния формы: Заявка (draft),
Заявка отправлена (sent), Заказ поставщику (purchase) и «Материал пришёл»
(pmk_metal_date).
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.pmk_sales_home.models.sales_home import MONTHS, WEEKDAYS, plural

TODO_LIMIT = 7
# Маяк свежести прайса: до двух недель — свежий, до месяца — пора запросить, дольше — устарел.
PRICE_FRESH_DAYS = 14
PRICE_OLD_DAYS = 30
NO_SUPPLIER = "pmk_tech.partner_no_supplier"
MISSING_SPEC_DAYS = 60


def tons(kg):
    kg = kg or 0.0
    if kg >= 1000:
        return ("%.1f т" % (kg / 1000)).replace(".", ",")
    return "%d кг" % round(kg)


def money(amount):
    amount = amount or 0.0
    if amount >= 1e6:
        return ("%.2f млн ₽" % (amount / 1e6)).replace(".", ",")
    if amount >= 1e3:
        return "%d тыс. ₽" % round(amount / 1e3)
    return "%d ₽" % round(amount)


def age_level(days):
    if days is None:
        return "none"
    if days <= PRICE_FRESH_DAYS:
        return "ok"
    if days <= PRICE_OLD_DAYS:
        return "warning"
    return "danger"


class PmkPurchaseHome(models.AbstractModel):
    _name = "pmk.purchase.home"
    _description = "Главная закупок"

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
        data["requests"] = self._requests(today)
        data["orders_metal"] = self._orders_metal()
        data["prices"] = self._prices(today)
        data["coverage"] = self._coverage(today)
        data["todo"] = self._todo(today, data)
        return data

    # ─── заявки на металл ───────────────────────────────────────────────
    def _requests(self, today):
        PO = self.env["purchase.order"]
        if "pmk_tech_spec_id" not in PO._fields or not PO.has_access("read"):
            return None
        try:
            orders = PO.search([("pmk_tech_spec_id", "!=", False), ("state", "!=", "cancel"),
                                "|", ("pmk_metal_date", "=", False),
                                ("pmk_metal_date", ">=", today - timedelta(days=30))])
        except AccessError:
            return None
        open_ = orders.filtered(lambda po: not po.pmk_metal_date)
        draft = open_.filtered(lambda po: po.state == "draft")
        sent = open_.filtered(lambda po: po.state in ("sent", "to approve"))
        ordered = open_.filtered(lambda po: po.state in ("purchase", "done"))
        week = orders.filtered(lambda po: po.pmk_metal_date and po.pmk_metal_date >= today - timedelta(days=7))
        month = orders.filtered("pmk_metal_date")

        def planned(po):
            return fields.Date.context_today(self, po.date_planned) if po.date_planned else None

        late = ordered.filtered(lambda po: planned(po) and planned(po) < today).sorted(planned)
        way_kg = sum(self._weight(po) for po in ordered)
        no_supplier = self.env.ref(NO_SUPPLIER, raise_if_not_found=False)
        orphan = open_.filtered(lambda po: no_supplier and po.partner_id == no_supplier)
        stages = [
            {"code": "draft", "label": "Заявка", "count": len(draft)},
            {"code": "sent", "label": "Отправлена", "count": len(sent)},
            {"code": "purchase", "label": "Заказ поставщику", "count": len(ordered)},
            {"code": "arrived", "label": "Пришло за неделю", "count": len(week)},
        ]
        lead = [(po.pmk_metal_date - fields.Date.context_today(self, po.date_order)).days
                for po in month if po.date_order]
        first_late = late[:1]
        return {
            "open": len(open_), "draft": len(draft), "late": len(late),
            "late_text": ("%s · %d %s" % (first_late.name, (today - planned(first_late)).days,
                                          plural((today - planned(first_late)).days, "день", "дня", "дней"))
                          if first_late else "все в срок"),
            "way_weight": tons(way_kg) if way_kg else "—",
            "way_amount": money(sum(ordered.mapped("amount_total"))) if ordered else "",
            "stages": stages,
            "month_weight": tons(sum(self._weight(po) for po in month)) if month else "",
            "month_amount": money(sum(month.mapped("amount_total"))) if month else "",
            "lead_days": round(sum(lead) / len(lead)) if lead else None,
            "count_word": plural(len(open_), "заявка", "заявки", "заявок"),
            "draft_text": "%d %s" % (len(draft), plural(len(draft), "не отправлена", "не отправлены",
                                                        "не отправлены")),
            "_late": late[:3].ids, "_draft": draft.sorted("date_order")[:2].ids, "_orphan": orphan[:2].ids,
        }

    def _weight(self, po):
        """Масса заявки: количество строки в единице товара × вес единицы (метр, лист, штука)."""
        kg = 0.0
        for line in po.order_line:
            product = line.product_id
            if not product or not product.weight:
                continue
            qty = line.product_qty
            if line.product_uom_id and product.uom_id and line.product_uom_id != product.uom_id:
                qty = line.product_uom_id._compute_quantity(qty, product.uom_id, raise_if_failure=False)
            kg += qty * product.weight
        return kg

    # ─── заказы ждут металл ─────────────────────────────────────────────
    def _orders_metal(self):
        Task = self.env["project.task"]
        if "pmk_is_order" not in Task._fields or not Task.has_access("read"):
            return None
        try:
            return {"count": Task.search_count([("pmk_is_order", "=", True),
                                                ("stage_id.pmk_order_stage", "=", "metal")])}
        except AccessError:
            return None

    # ─── прайсы: маяк свежести ──────────────────────────────────────────
    def _prices(self, today):
        Partner = self.env["res.partner"]
        if "pmk_price_supplier" not in Partner._fields or not Partner.has_access("read"):
            return None
        try:
            suppliers = Partner.search([("pmk_price_supplier", "=", True)])
        except AccessError:
            return None
        Info = self.env["product.supplierinfo"]
        counts = {}
        if Info.has_access("read"):
            groups = Info._read_group([("partner_id", "in", suppliers.ids), "|", ("date_end", "=", False),
                                       ("date_end", ">=", today)], ["partner_id"], ["__count"])
            counts = {partner.id: count for partner, count in groups}
        rows = []
        for partner in suppliers:
            last = partner.pmk_price_last_date
            if not last:
                continue
            days = (today - last).days
            rows.append({"id": partner.id, "name": self._short(partner.name, 34),
                         "date": last.strftime("%d.%m.%Y" if last.year != today.year else "%d.%m"),
                         "days": days, "age": "%d %s" % (days, plural(days, "день", "дня", "дней")),
                         "level": age_level(days), "count": counts.get(partner.id, 0)})
        rows.sort(key=lambda r: r["days"])
        latest = rows[0] if rows else None
        mailing = self._mailing()
        return {
            "rows": rows[:6], "more": max(0, len(rows) - 6),
            "with_price": len(rows), "total": len(suppliers),
            "without": len(suppliers) - len(rows),
            "latest_date": latest["date"] if latest else "—",
            "latest_age": latest["age"] if latest else "прайсов нет",
            "latest_level": latest["level"] if latest else "none",
            "mailing": mailing,
        }

    def _mailing(self):
        ICP = self.env["ir.config_parameter"].sudo()
        if not self.env.user.has_group("purchase.group_purchase_user"):
            return None
        on = ICP.get_param("pmk.price_request.enabled", "0") == "1"
        return {"on": on, "text": _("включена") if on else _("выключена")}

    # ─── покрытие ценами ────────────────────────────────────────────────
    def _coverage(self, today):
        out = {"rows": [], "missing": []}
        for key, model, label in (("profile", "pmk.metal.profile", _("Прокат")),
                                  ("sheet", "pmk.metal.sheet", _("Лист")),
                                  ("fastener", "pmk.metal.fastener", _("Метизы"))):
            if model not in self.env or not self.env[model].has_access("read"):
                continue
            Model = self.env[model]
            if "product_tmpl_id" not in Model._fields:
                continue
            base = [("pmk_pending", "=", False)] if "pmk_pending" in Model._fields else []
            total = Model.search_count(base)
            priced = Model.search_count(base + [("product_tmpl_id.seller_ids", "!=", False)])
            out["rows"].append({"key": key, "label": label, "priced": priced, "total": total,
                                "pct": round(100.0 * priced / total) if total else 0})
        Line = self.env["pmk.metal.spec.line"]
        if "price_state" in Line._fields and Line.has_access("read"):
            since = fields.Datetime.now() - timedelta(days=MISSING_SPEC_DAYS)
            lines = Line.search([("price_state", "=", "no_price"), ("spec_id.write_date", ">=", since)])
            agg = {}
            for line in lines:
                item = line.profile_id or line.sheet_id or line.fastener_id
                if not item:
                    continue
                key = (item._name, item.id)
                row = agg.setdefault(key, {"name": item.display_name, "specs": set(), "kg": 0.0})
                row["specs"].add(line.spec_id.id)
                row["kg"] += (line.weight_fact_total or 0.0) * (line.product_id.qty or 1)
            ranked = sorted(agg.values(), key=lambda r: -r["kg"])[:5]
            out["missing"] = [{"name": self._short(r["name"], 40),
                               "sub": "в %d %s · %s" % (len(r["specs"]), plural(len(r["specs"]), "расчёте",
                                                                                 "расчётах", "расчётах"), tons(r["kg"]))}
                              for r in ranked]
        profile = next((r for r in out["rows"] if r["key"] == "profile"), None)
        out["profile_missing"] = (profile["total"] - profile["priced"]) if profile else None
        return out

    # ─── «Сделать сегодня» ──────────────────────────────────────────────
    def _todo(self, today, data):
        items = []
        req = data.get("requests") or {}
        PO = self.env["purchase.order"]
        for po in PO.browse(req.get("_late") or []):
            planned = fields.Date.context_today(self, po.date_planned)
            items.append({"kind": "po", "id": po.id, "level": "danger", "tag": _("поставка"),
                          "title": "%s, %s" % (po.name, po.partner_id.name or ""),
                          "sub": _("обещали %s · ждут %s") % (planned.strftime("%d.%m"),
                                                            self._order_name(po) or _("заказ"))})
        for po in PO.browse(req.get("_draft") or []):
            items.append({"kind": "po", "id": po.id, "level": "warning", "tag": _("отправить"),
                          "title": _("Заявка %s · %s") % (po.name, tons(self._weight(po))),
                          "sub": _("собрана %s, не ушла поставщику") % fields.Date.context_today(
                              self, po.date_order).strftime("%d.%m")})
        for po in PO.browse(req.get("_orphan") or []):
            names = ", ".join(po.order_line[:2].mapped(lambda l: l.product_id.display_name or l.name or ""))
            items.append({"kind": "po", "id": po.id, "level": "warning", "tag": _("поставщик"),
                          "title": _("%d %s без поставщика") % (len(po.order_line), plural(
                              len(po.order_line), "позиция", "позиции", "позиций")),
                          "sub": "%s: %s" % (po.name, self._short(names, 60))})
        for spec in self._tech_without_request()[:2]:
            items.append({"kind": "spec", "id": spec.id, "level": "warning", "tag": _("расчёт"),
                          "title": _("Технический расчёт без заявки"),
                          "sub": " · ".join(p for p in (spec.name, spec.pmk_tech_order_id.name,
                                                         spec.pmk_tech_order_id.partner_id.name) if p)})
        prices = data.get("prices") or {}
        old = [r for r in prices.get("rows") or [] if r["level"] == "danger"]
        for row in old[:1]:
            items.append({"kind": "supplier", "id": row["id"], "level": "neutral", "tag": _("прайс"),
                          "title": _("%s — прайс от %s") % (row["name"], row["date"]),
                          "sub": _("%s назад, запросить свежий") % row["age"]})
        for key in ("_late", "_draft", "_orphan"):
            req.pop(key, None)
        return items[:TODO_LIMIT]

    def _order_name(self, po):
        spec = po.pmk_tech_spec_id
        order = spec.pmk_tech_order_id if spec and "pmk_tech_order_id" in spec._fields else False
        return order.name if order else ""

    def _tech_without_request(self):
        Spec = self.env["pmk.metal.spec"]
        PO = self.env["purchase.order"]
        if "pmk_kind" not in Spec._fields or not Spec.has_access("read") or not PO.has_access("read"):
            return Spec.browse()
        try:
            specs = Spec.search([("pmk_kind", "=", "tech"), ("pmk_tech_order_id", "!=", False)],
                                order="create_date desc", limit=30)
            with_po = set(PO.search([("pmk_tech_spec_id", "in", specs.ids)]).mapped("pmk_tech_spec_id").ids)
        except AccessError:
            return Spec.browse()
        return specs.filtered(lambda s: s.id not in with_po)

    @staticmethod
    def _short(text, limit):
        text = text or ""
        return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"

    # ─── переходы ───────────────────────────────────────────────────────
    @api.model
    def open_block(self, key, res_id=False):
        requests = "pmk_tech.action_metal_requests"
        form = lambda model: {"type": "ir.actions.act_window", "res_model": model, "res_id": res_id,  # noqa: E731
                              "views": [[False, "form"]], "target": "current"}
        if key == "requests":
            return self._action(requests)
        if key == "stage" and isinstance(res_id, str):
            domain = {"draft": [("state", "=", "draft"), ("pmk_metal_date", "=", False)],
                      "sent": [("state", "in", ("sent", "to approve")), ("pmk_metal_date", "=", False)],
                      "purchase": [("state", "in", ("purchase", "done")), ("pmk_metal_date", "=", False)],
                      "arrived": [("pmk_metal_date", ">=", fields.Date.context_today(self) - timedelta(days=7))],
                      "late": [("state", "in", ("purchase", "done")), ("pmk_metal_date", "=", False),
                               ("date_planned", "<", fields.Datetime.now())]}.get(res_id)
            if domain is None:
                return False
            action = self._action(requests)
            if action:
                action["domain"] = [("pmk_tech_spec_id", "!=", False), ("state", "!=", "cancel")] + domain
                action["context"] = {"create": False}
            return action
        if key == "po" and res_id:
            return form("purchase.order")
        if key == "spec" and res_id:
            return form("pmk.metal.spec")
        if key == "supplier" and res_id:
            return form("res.partner")
        if key == "orders_metal":
            return self._action("pmk_orders.action_orders", domain=[("stage_id.pmk_order_stage", "=", "metal")])
        if key == "suppliers":
            return self._action("pmk_purchase.action_price_supplier")
        if key == "prices":
            return self._action("pmk_purchase.action_supplier_prices")
        if key == "mailing":
            try:
                return self.env["ir.actions.actions"]._for_xml_id("pmk_purchase.action_price_mailing")
            except (ValueError, AccessError):
                return False
        if key == "missing":
            return self._action("pmk_calc.action_metal_profile", name=_("Прокат без цены"),
                                domain=[("product_tmpl_id.seller_ids", "=", False), ("pmk_pending", "=", False)])
        return False

    def _action(self, xmlid, domain=None, name=None):
        try:
            action = dict(self.env["ir.actions.act_window"]._for_xml_id(xmlid))
        except (ValueError, AccessError):
            return False
        if domain is not None:
            action["domain"] = domain
        if name:
            # Odoo 19 подписывает хлебные крошки display_name действия, а не name.
            action["name"] = action["display_name"] = name
        return action
