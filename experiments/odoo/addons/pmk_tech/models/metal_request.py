# -*- coding: utf-8 -*-
"""«Заявка на металл»: металл технического расчёта → черновики закупок (шаг З-4).

СБОР (_pmk_metal_rows). Позиция заявки — товар справочника (карточка
номенклатуры, мост pmk_bridge), у листа — товар и габарит:

  • прокат — метры: длина × кол-во на изделие × изделий / использование
    (как «Металл к закупке» расчёта), в описании «≈ N хлыстов по L м», если
    длина хлыста есть в строке прайса;
  • лист — ЧИСЛОМ ЛИСТОВ РАСКЛАДКИ (layout_sheets деталей «Посчитана» /
    «Деталь в размер листа»). Деталь без раскладки (не раскладывали, правили
    после, деталь больше листа) — по весу: её килограммы делятся на массу
    листа габарита и округляются вверх — и плашка «в заявке по весу». Масса
    листа — масса м² справочника × площадь габарита, не вес карточки (мина
    1500×6000, шаг 57, здесь не трогаем);
  • метизы — штуки; покрытие — килограммы; услуга («не материал»,
    цинкование на стороне) в заявку не идёт.

ЦЕНА ЗА ЕДИНИЦУ ЗАКАЗА — по прайсу того поставщика, у которого её взял
расчёт (price_partner_id: назначенный поставщик позиции, правило
_pmk_find_seller моста — рейтинг, базовый уровень объёма): Σ стоимости /
количество. У листа — цена за кг × масса листа габарита (для 1500×6000 это
и есть цена листа в прайсе). Цена задана явно: ядро не пересчитает её по
оптовым порогам, пока закупщик сам не поменяет количество или поставщика.
Лист НЕ 1500×6000 — цена ручная (technical_price_unit ≠ price_unit): строка
прайса заведена за лист 1500×6000, и ядро, перечитав её после правки
количества, молча поставило бы цену вдвое выше (мина шага 57). Лист такого
габарита без цены в прайсах — та же мина: выбрав поставщика, закупщик
получит цену листа 1500×6000 (разобрать в шаге 57).

БЕЗ ЦЕНЫ — СИГНАЛ «В ГОРОДЕ НЕТ», НЕ ОШИБКА. Соседний размер не
подставляем: позиция уходит в черновик на служебного «Поставщик не
выбран» (data/partner.xml) с ценой 0 — закупщик видит её в «Заявках на
металл» и выбирает поставщика сам.

ПОВТОР БЕЗ ДУБЛЕЙ (_pmk_sync_requests). Ключ позиции — в строке заказа
(pmk_request_key):
  • черновик — обновляется: количество, цена (если поставщик тот же),
    описание; позиция пропала из расчёта — строка удаляется; опустевший
    черновик — отменяется (не удаляется);
  • НО ПРАВКИ ЗАКУПЩИКА ЦЕЛЫ: поле строки, которое закупщик поменял после
    заявки (количество, цена, описание — сравнение с записанным заявкой,
    pmk_request_*), повтор не перезаписывает; строку, которую он правил,
    не удаляет и к другому поставщику не переносит. Расхождение количества
    с инженером — плашкой технического расчёта, как у отправленной;
  • отправленную поставщику и подтверждённую заявку не трогаем —
    расхождение показывает плашка технического расчёта («в заявке 11
    листов, у инженера 12»);
  • новая позиция — в черновик своего поставщика (нет — новый);
  • позиция из «Поставщик не выбран», у которой нашлась цена, переезжает в
    черновик поставщика.
Сопоставление — по ключу через все черновики расчёта: закупщик сменил
поставщика в черновике — повтор не заведёт второй.

ПЛАНИРОВЩИК. Строка «Заказов в работе» ЭТОГО счёта (не всей сделки: у
сделки бывает второй счёт со своей строкой; строку сделки без счёта —
только если у счёта своей нет): «Металл» — «Ждём», этап из «Очереди» /
«Разработки чертежей» — «Ждём металл»; дальше (в работе, пауза, готово,
отгружено) и этап без кода («Разобрать: прошлые месяцы», импорт) не
трогаем.

ПИСЕМ НЕТ: черновики не отправляются, подписчиков не добавляем, лента —
заметками (_message_log). Отправка поставщику — штатной кнопкой закупщика.
"""
import math

from markupsafe import Markup, escape

from odoo import Command, _, api, models
from odoo.exceptions import UserError
from odoo.tools.misc import clean_context

from odoo.addons.pmk_calc.models.sheeting import SHEET_USE_COUNTED
from odoo.addons.pmk_calc.models.spec_layout import _plural

from .metal_spec import EPS, _num

MODE_ORDER = {"linear": 0, "sheet": 1, "fastener": 2, "paint": 3}
DEFAULT_SIZE = "1500x6000"


def _add_once(items, text):
    if text and text not in items:
        items.append(text)


class MetalSpecRequest(models.Model):
    _inherit = "pmk.metal.spec"

    # ─── Сбор металла ───────────────────────────────────────────────────
    def _pmk_metal_rows(self):
        """→ (позиции заявки по порядку, заметки). Позиция — словарь:
        key, mode, name, position, product, partner, priced, seller, qty,
        price, kg, cost, unlaid, size, label."""
        self.ensure_one()
        placeholder = self.env["purchase.order"]._pmk_no_supplier_partner(create=False)
        acc = {}
        notes = {"unlaid": [], "no_card": [], "service": []}
        for product in self.product_ids:
            count = product.qty or 0
            if count <= 0:
                continue
            for line in product.line_ids:
                position = line._cost_position()
                if not position:
                    continue
                mode = line.calc_mode
                if mode == "paint" and position.pmk_not_material:
                    _add_once(notes["service"], position.display_name)
                    continue
                tmpl = position.product_tmpl_id
                variant = line.price_source_id.product_id or tmpl.product_variant_id
                if not tmpl or not variant:
                    _add_once(notes["no_card"], position.display_name)
                    continue
                size = (line.layout_sheet_size or DEFAULT_SIZE) if mode == "sheet" else ""
                key = "%s:%s%s" % (mode, tmpl.id, (":" + size) if size else "")
                row = acc.get(key)
                if row is None:
                    row = acc[key] = {
                        "key": key, "mode": mode, "name": position.display_name,
                        "position": position, "product": variant, "size": size,
                        "partner": None, "seller": None,
                        "qty": 0.0, "kg": 0.0, "priced_qty": 0.0, "priced_cost": 0.0,
                        "laid": 0, "unlaid_kg": 0.0, "unlaid": 0,
                    }
                priced = line.price_state == "ok" and bool(line.price_partner_id)
                if priced and row["partner"] is None:
                    row["partner"] = line.price_partner_id
                    row["seller"] = line.price_source_id
                if mode == "sheet":
                    net = (line.weight_total or 0.0) * count
                    if line.layout_state in SHEET_USE_COUNTED and line.layout_sheets:
                        row["laid"] += line.layout_sheets
                    elif net:
                        row["unlaid_kg"] += net
                        row["unlaid"] += 1
                    if priced and net:
                        row["priced_qty"] += net
                        row["priced_cost"] += (line.price_kg or 0.0) * net
                    continue
                if mode == "linear":
                    share = (line.utilization_pct or 100.0) / 100.0
                    qty = ((line.length_mm or 0.0) / 1000.0 * (line.qty or 0) * count / share
                           if share else 0.0)
                elif mode == "fastener":
                    qty = float((line.qty or 0) * count)
                else:
                    qty = (line.weight_total or 0.0) * count
                row["qty"] += qty
                row["kg"] += (line.weight_fact_total or 0.0) * count
                if priced:
                    row["priced_qty"] += qty
                    row["priced_cost"] += (line.cost_fact_total or 0.0) * count

        rows = []
        for row in acc.values():
            if row["mode"] == "sheet":
                width, length = (float(part) for part in row["size"].split("x"))
                sheet_kg = (row["position"].mass_per_sqm or 0.0) * width * length / 1e6
                by_weight = 0
                if row["unlaid_kg"] and sheet_kg:
                    by_weight = math.ceil(row["unlaid_kg"] / sheet_kg - 1e-6)
                sheets = row["laid"] + by_weight
                price_kg = row["priced_cost"] / row["priced_qty"] if row["priced_qty"] else 0.0
                row.update(qty=float(sheets), kg=sheets * sheet_kg, price=price_kg * sheet_kg)
                if row["unlaid"]:
                    _add_once(notes["unlaid"], "%s %s" % (row["name"], self._pmk_size_label(row["size"])))
            else:
                digits = 0 if row["mode"] == "fastener" else 2
                row["qty"] = round(row["qty"], digits)
                row["price"] = (row["priced_cost"] / row["priced_qty"]) if row["priced_qty"] else 0.0
            if row["qty"] <= 0:
                continue
            row["priced"] = bool(row["partner"]) and bool(row["price"])
            if not row["priced"]:
                row.update(partner=placeholder, price=0.0)
            row["cost"] = row["price"] * row["qty"]
            # Лист не 1500×6000: цена — наша, не строки прайса (см. выше).
            row["manual_price"] = (row["mode"] == "sheet" and row["size"] != DEFAULT_SIZE
                                   and bool(row["price"]))
            row["label"] = self._pmk_row_label(row)
            rows.append(row)
        rows.sort(key=lambda r: (MODE_ORDER.get(r["mode"], 9), r["name"] or ""))
        return rows, notes

    @api.model
    def _pmk_size_label(self, size):
        selection = dict(self.env["pmk.metal.spec.line"]._fields["layout_sheet_size"].selection)
        return selection.get(size, size or "")

    @api.model
    def _pmk_qty_text(self, mode, qty):
        if mode == "sheet":
            count = int(round(qty or 0))
            return "%s %s" % (count, _plural(count, "лист", "листа", "листов"))
        if mode == "fastener":
            return "%s шт" % _num(qty, 0)
        if mode == "paint":
            return "%s кг" % _num(qty, 2)
        return "%s м" % _num(qty, 2)

    def _pmk_row_label(self, row):
        """Описание строки заказа — что и сколько, словами закупщика."""
        qty = self._pmk_qty_text(row["mode"], row["qty"])
        weight = self._pmk_weight_label(row["kg"]) if row["kg"] else ""
        if row["mode"] == "sheet":
            text = "%s, %s — %s" % (row["name"], self._pmk_size_label(row["size"]), qty)
            if weight:
                text += ", %s" % weight
            # «По весу, без раскладки» — заметка завода, не поставщику:
            # описание строки печатается в бланке и уходит в письме. Она —
            # в плашке технического расчёта и в его ленте.
            return text
        text = "%s — %s" % (row["name"], qty)
        bar = row["seller"].pmk_bar_length_mm if row["seller"] else 0.0
        if row["mode"] == "linear" and bar:
            bars = math.ceil(row["qty"] * 1000.0 / bar - 1e-6)
            text += ", ≈ %s %s по %s м" % (
                bars, _plural(bars, "хлыст", "хлыста", "хлыстов"), _num(bar / 1000.0, 2))
        if weight and row["mode"] != "paint":
            text += ", %s" % weight
        return text

    # ─── Кнопка ─────────────────────────────────────────────────────────
    def action_pmk_metal_request(self):
        """«Заявка на металл»: черновики закупок по поставщикам, строка
        планировщика — «Ждём металл». Ничего не блокирует: без раскладки —
        листы по весу, без цены — «Поставщик не выбран»."""
        self.ensure_one()
        if self.pmk_kind != "tech":
            raise UserError(_(
                "«Заявка на металл» собирается из технического расчёта — откройте его "
                "кнопкой «Технический расчёт» в счёте покупателю или в «Заказах в работе»."))
        rows, notes = self._pmk_metal_rows()
        result = self._pmk_sync_requests(rows)
        tasks = self._pmk_planner_wait_metal(result)
        self._pmk_log_request(rows, notes, result, tasks)
        return self.env["purchase.order"]._pmk_requests_window(
            [("pmk_tech_spec_id", "=", self.id)], orders=result["orders"])

    def _pmk_request_context(self):
        return dict(clean_context(self.env.context),
                    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True)

    def _pmk_request_planner_rows(self):
        """Строки «Заказов в работе» счёта технического расчёта (и архивные).

        _pmk_planner_rows (pmk_orders) отдаёт строки счёта ИЛИ всей сделки: у
        сделки со вторым счётом заявка по счёту А тронула бы строку счёта Б,
        а карточка 5 («Материал пришёл») отметила бы металл не у того
        заказа. Берём строки этого счёта; строку сделки без счёта — только
        если у счёта своей нет."""
        self.ensure_one()
        order = self.pmk_tech_order_id
        if not order:
            return self.env["project.task"].sudo()
        rows = order._pmk_planner_rows()
        return (rows.filtered(lambda row: row.pmk_sale_order_id == order)
                or rows.filtered(lambda row: not row.pmk_sale_order_id))

    def _pmk_planner_task(self):
        """Строка «Заказов в работе» счёта (действующая — первой)."""
        self.ensure_one()
        rows = self._pmk_request_planner_rows()
        return (rows.filtered("active") or rows)[:1]

    def _pmk_sync_requests(self, rows):
        self.ensure_one()
        PO = self.env["purchase.order"].with_context(self._pmk_request_context())
        placeholder = PO._pmk_no_supplier_partner()
        orders = self.pmk_metal_request_ids.with_env(PO.env).filtered(
            lambda order: order.state != "cancel")
        locked, drafts = {}, {}
        for order in orders.sorted("id"):
            for line in order.order_line:
                if line.pmk_request_key:
                    target = drafts if order.state == "draft" else locked
                    target.setdefault(line.pmk_request_key, line)
        res = {"created": PO.browse(), "updated": PO.browse(), "cancelled": PO.browse(),
               "orders": PO.browse(), "added": [], "removed": [], "locked": [], "kept": []}
        fresh = {}
        for row in rows:
            if not row["partner"]:
                row["partner"] = placeholder
            key = row["key"]
            if key in locked:
                res["locked"].append(row)
                res["orders"] |= locked[key].order_id
                continue
            line = drafts.pop(key, None)
            edits = line._pmk_request_edits() if line else set()
            if (line and not edits and line.order_id.partner_id == placeholder
                    and row["partner"] != placeholder):
                # Цена нашлась — позиция переезжает к своему поставщику
                # (строку, которую правил закупщик, не переносим).
                res["updated"] |= line.order_id
                line.unlink()
                line = None
            if line:
                order = line.order_id
                changed, kept = self._pmk_update_request_line(line, row, edits)
                if kept:
                    res["kept"].append((row, kept))
                if changed:
                    res["updated"] |= order
                res["orders"] |= order
                continue
            fresh.setdefault(row["partner"], []).append(row)

        for line in drafts.values():
            if line._pmk_request_edits():
                # Позиции у инженера нет, а строку правил закупщик — не
                # удаляем молча: «у инженера нет» покажет плашка расхождения.
                if line._pmk_request_requested_qty():
                    line._pmk_stamp_request(qty=0.0, keep=("price", "name"))
                res["kept"].append(({"name": line.product_id.display_name or line.name},
                                    {"removed"}))
                res["orders"] |= line.order_id
                continue
            res["removed"].append(line.name)
            res["updated"] |= line.order_id
            line.unlink()

        task = self._pmk_planner_task()
        for partner, partner_rows in fresh.items():
            commands = [Command.create(self._pmk_request_line_vals(row)) for row in partner_rows]
            order = (orders | res["created"]).filtered(
                lambda o: o.state == "draft" and o.partner_id == partner)[:1]
            if order:
                order.write({"order_line": commands})
                res["updated"] |= order
            else:
                order = PO.create(self._pmk_request_order_vals(partner, commands, task))
                res["created"] |= order
            res["orders"] |= order
            res["added"] += partner_rows
            keys = {row["key"]: row for row in partner_rows}
            new_lines = order.order_line.filtered(
                lambda line: line.pmk_request_key in keys and not line.pmk_request_name)
            for line in new_lines:
                if keys[line.pmk_request_key]["manual_price"]:
                    line.technical_price_unit = 0.0
            new_lines._pmk_stamp_request()

        for order in (orders | res["created"]).filtered(
                lambda o: o.state == "draft" and not o.order_line):
            order.button_cancel()
            res["cancelled"] |= order
        res["orders"] = res["orders"].filtered(lambda o: o.state != "cancel")
        res["updated"] = (res["updated"] - res["created"]).filtered(lambda o: o.state != "cancel")
        if task:
            res["orders"].filtered(lambda o: not o.pmk_task_id).write({"pmk_task_id": task.id})
        return res

    @api.model
    def _pmk_update_request_line(self, line, row, edits):
        """Черновик: записать в строку то, что поменялось у инженера, кроме
        полей, которые правил закупщик (edits). → (записали ли что-то,
        какие правки закупщика расходятся с инженером и оставлены)."""
        vals = {}
        same_partner = line.order_id.partner_id == row["partner"]
        differs = {
            "qty": abs(line.product_qty - row["qty"]) > EPS,
            "price": same_partner and abs(line.price_unit - row["price"]) >= EPS,
            "name": (line.name or "") != row["label"],
        }
        kept = {name for name in edits if differs.get(name)}
        if "qty" not in edits and differs["qty"]:
            vals["product_qty"] = row["qty"]
        if ("price" not in edits and same_partner
                and (vals or differs["price"])):
            # Цена вместе с количеством: одно количество ядро пересчитало бы
            # по оптовым порогам прайса. technical_price_unit — тоже: иначе
            # ядро сочтёт цену ручной и при смене поставщика в черновике не
            # перечитает её по его прайсу (у листа не 1500×6000 — ручная).
            vals["price_unit"] = row["price"]
            vals["technical_price_unit"] = 0.0 if row["manual_price"] else row["price"]
        if "name" not in edits and differs["name"]:
            vals["name"] = row["label"]
        if vals:
            line.write(vals)
        requested = line._pmk_request_requested_qty()
        if vals or abs(requested - row["qty"]) > EPS or not line.pmk_request_name:
            line._pmk_stamp_request(qty=row["qty"] if "qty" in edits else None, keep=edits)
        return bool(vals), kept

    def _pmk_request_origin(self):
        self.ensure_one()
        parts = ["%s (тех.)" % self.name]
        if self.pmk_tech_order_id:
            parts.append(self.pmk_tech_order_id.name)
        return ", ".join(parts)

    def _pmk_request_order_vals(self, partner, commands, task):
        self.ensure_one()
        order = self.pmk_tech_order_id
        deal = order.opportunity_id or self.opportunity_id
        return {
            "partner_id": partner.id,
            "company_id": (self.company_id or self.env.company).id,
            "origin": self._pmk_request_origin(),
            "pmk_tech_spec_id": self.id,
            "pmk_sale_order_id": order.id or False,
            "pmk_deal_id": deal.id or False,
            "pmk_task_id": task.id or False,
            "order_line": commands,
        }

    @api.model
    def _pmk_request_line_vals(self, row):
        product = row["product"]
        return {
            "product_id": product.id,
            "name": row["label"],
            "product_qty": row["qty"],
            "product_uom_id": product.uom_id.id,
            # Явная цена: ядро считает её заданной (technical_price_unit =
            # price_unit при создании) и при создании не трогает. Лист не
            # 1500×6000 после создания помечается ручной ценой (sync).
            "price_unit": row["price"],
            "pmk_request_key": row["key"],
        }

    # ─── Планировщик ────────────────────────────────────────────────────
    def _pmk_planner_wait_metal(self, res):
        """Строка счёта: «Металл» — «Ждём», «Очередь» / «Разработка
        чертежей» → «Ждём металл». Получен и ничего нового не заказали —
        «Получен» остаётся. Нет строки или проекта — ничего не делаем."""
        self.ensure_one()
        if not self.pmk_tech_order_id or not res["orders"]:
            return self.env["project.task"]
        tasks = self._pmk_request_planner_rows().filtered(
            lambda row: row.active and row.project_id.pmk_is_orders)
        ordered_new = bool(res["created"] or res["added"])
        for task in tasks:
            vals = {}
            if task.pmk_metal != "wait" and (task.pmk_metal != "got" or ordered_new):
                vals["pmk_metal"] = "wait"
            # Этап без кода («Разобрать: прошлые месяцы» — импорт, строка
            # может быть уже в работе или отгружена) не трогаем: только
            # «Металл: Ждём».
            if task.stage_id.pmk_order_stage in ("queue", "drawings"):
                stage = task.project_id.type_ids.filtered(
                    lambda s: s.pmk_order_stage == "metal").sorted("sequence")[:1]
                if stage and stage != task.stage_id:
                    vals["stage_id"] = stage.id
            if vals:
                # sudo — права на строку (у инженера «Проекты» есть, у
                # продавца — правило pmk_orders); автор истории — тот, кто
                # нажал (sudo пользователя не меняет).
                task.sudo().with_context(mail_auto_subscribe_no_notify=True).write(vals)
        return tasks

    # ─── Лента ──────────────────────────────────────────────────────────
    def _pmk_log_request(self, rows, notes, res, tasks):
        self.ensure_one()
        items = []
        for order in res["orders"].sorted("id"):
            if order in res["created"]:
                verb = _("новая")
            elif order in res["updated"]:
                verb = _("обновлена")
            else:
                verb = _("без изменений")
            lines = order.order_line.filtered("pmk_request_key")
            what = Markup("; ").join(escape(line.name or "") for line in lines)
            items.append(Markup("<li>%s, %s (%s): %s</li>") % (
                order._get_html_link(), order.partner_id.display_name, verb, what))
        if not rows:
            body = Markup("<p>%s</p>") % _(
                "Заявка на металл: металла в расчёте нет — заказывать нечего.")
        else:
            body = Markup("<p>%s</p><ul>%s</ul>") % (
                _("Заявка на металл — черновики закупок по поставщикам:"),
                Markup("").join(items))
        extra = []
        unpriced = [row["name"] for row in rows if not row["priced"]]
        if unpriced:
            extra.append(_("Поставщик не выбран (нет цены в прайсах — в городе нет): %s.",
                           ", ".join(unpriced)))
        if res["locked"]:
            extra.append(_("Отправленные поставщику и подтверждённые заявки не меняли: %s.",
                           ", ".join(row["name"] for row in res["locked"])))
        if res["kept"]:
            words = {"qty": _("количество"), "price": _("цена"), "name": _("описание"),
                     "removed": _("строка — у инженера позиции нет")}
            extra.append(_("Правки закупщика в черновиках сохранены: %s.", "; ".join(
                "%s (%s)" % (row["name"], ", ".join(words[w] for w in ("qty", "price", "name", "removed")
                                                    if w in edits))
                for row, edits in res["kept"])))
        if res["removed"]:
            extra.append(_("Убрано из черновиков (нет в расчёте): %s.", ", ".join(res["removed"])))
        if res["cancelled"]:
            extra.append(_("Опустевшие черновики отменены: %s.",
                           ", ".join(res["cancelled"].mapped("name"))))
        warn = self._pmk_warn_text(notes)
        if warn:
            extra.append(warn + ".")
        metal = dict(self.env["project.task"]._fields["pmk_metal"].selection)
        for task in tasks:
            extra.append(_("Заказ в работе «%(row)s»: этап «%(stage)s», металл «%(metal)s».",
                           row=task.name, stage=task.stage_id.name or "—",
                           metal=metal.get(task.pmk_metal, "—")))
        for text in extra:
            body += Markup("<p>%s</p>") % text
        self._message_log(body=body)


class PurchaseOrderRequests(models.Model):
    _inherit = "purchase.order"

    @api.model
    def _pmk_requests_window(self, domain, orders=None):
        """Окно «Заявки на металл»: одна заявка — её форма, иначе список."""
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_tech.action_metal_requests")
        if orders is not None and len(orders) == 1:
            action.update(res_id=orders.id, view_mode="form",
                          views=[(False, "form")], name=orders.name)
            return action
        action["domain"] = list(domain)
        return action
