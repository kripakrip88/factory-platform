# -*- coding: utf-8 -*-
"""«Технический расчёт» — копия расчёта КП для инженера (шаг З-4).

Решение Антона 08.10.2026: «инженер работает в Техническом расчёте — копии
расчёта менеджера у той же сделки; расчёт, по которому ушло КП/счёт, остаётся
нетронутым (видно, сколько металла было в КП и сколько по факту)».

ВИД РАСЧЁТА — СВОЙ ПРИЗНАК (pmk_kind), а не «есть ссылка на исходный».
Ссылка на расчёт КП обнуляется, если тот удалят (set null), — и технический
тихо превратился бы в расчёт КП, а с ним и в главный расчёт сделки.

ОДИН ТЕХНИЧЕСКИЙ НА СЧЁТ (уникальный индекс): кнопка «Технический расчёт» в
счёте и в строке планировщика заводит его один раз, дальше открывает тот же.

КОПИЯ — ШТАТНАЯ copy() РАСЧЁТА: изделия и детали (copy=True), сделка
(pmk_deal), организация (pmk_org), дата и цены закупки — на сегодня (pmk_calc,
pmk_bridge: цены перечитаны из прайсов). Раскладка листов в копию сама не
идёт (copy=False, приёмка 01.10, R4) — её переносим явно: инженер начинает с
того, что посчитал менеджер, и «Заявка на металл» сразу знает число листов.
Отпечаток раскладки (шаг 56) — тот же: плашка «Раскладка устарела» ведёт себя
как у расчёта КП.

ТЕХНИЧЕСКИЙ НЕ ГЛАВНЫЙ И НЕ КП. Главный расчёт сделки выбирается без него
(_pmk_main_spec_candidates, pmk_deal) — иначе он подменил бы «Цену клиенту» и
карточки денег сделки. «КП (PDF)» и «Отправить КП» у него спрятаны, а если
письмо КП всё же уйдёт — стадия сделки не меняется и счёт из него не
выставляется (_pmk_kp_move_stage).

СРАВНЕНИЕ «МЕТАЛЛ В ЗАЯВКУ: ПО КП → СЕЙЧАС» — карточкой на форме вместо
карточки моста «Металл к закупке» (та считает чистый вес деталей, а заявка —
целые листы раскладки: два разных «к закупке» на одном экране). Обе части —
одной мерой, _pmk_metal_rows: по расчёту КП (его раскладка скопирована) и
по техническому. Состав не трогали — числа совпадают; разница — только
правки инженера (и цены на сегодня в рублях).
Плашки: что в заявку идёт по весу (листы без раскладки), что в неё не идёт
(нет карточки товара, услуга), что изменилось после заявки, что расходится с
заявкой (отправленной, подтверждённой или черновиком, где количество правил
закупщик) и что счёт изменился после копии (новая редакция или выставлен из
другого расчёта: сверить состав). Ничего не блокирует.

«ДУБЛИРОВАТЬ» ТЕХНИЧЕСКИЙ — тоже технический (copy_data): иначе копия
получила бы вид «Для КП» и стала бы главным расчётом сделки. Счёт копии не
переносится (один технический на счёт) — она вариант инженера, заявку из
неё можно собрать, но к строке планировщика она не привязана.
"""
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools.misc import clean_context

from odoo.addons.pmk_calc.models.spec_layout import LAYOUT_RESULTS

from .purchase_order import EPS, REQUEST_STATE_LABELS

KINDS = [("kp", "Для КП"), ("tech", "Технический")]


def _num(value, digits=0):
    """Число по-русски: «1 554», «1,104», «36,5» (лишние нули дроби — прочь)."""
    text = "{:,.{d}f}".format(value or 0.0, d=digits).replace(",", " ").replace(".", ",")
    if digits and "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def _tons(kg):
    """Тонны до килограмма, без единицы: «1,554», «0,267», «12»."""
    return _num((kg or 0.0) / 1000.0, 3)


def _rub(amount):
    return "%s ₽" % _num(amount, 0)


class MetalSpecTech(models.Model):
    _inherit = "pmk.metal.spec"

    pmk_kind = fields.Selection(
        KINDS, "Вид", default="kp", index=True, copy=False, readonly=True,
        help="«Для КП» — расчёт менеджера: по нему КП и счёт. «Технический» — "
             "копия инженера к счёту покупателю: по ней заявка на металл; "
             "расчёт КП при этом не меняется.")
    pmk_tech_source_id = fields.Many2one(
        "pmk.metal.spec", "Расчёт КП", index=True, ondelete="set null",
        copy=False, readonly=True,
        help="С какого расчёта менеджера снята копия — по нему ушли КП и счёт.")
    pmk_tech_order_id = fields.Many2one(
        "sale.order", "Счёт покупателю", index=True, ondelete="set null",
        copy=False, readonly=True,
        help="К какому счёту покупателю технический расчёт.")
    pmk_tech_revision = fields.Integer(
        "Редакция счёта при копии", copy=False, readonly=True,
        help="Какая редакция счёта была, когда сняли технический расчёт: "
             "редакция выросла — счёт менялся после копии, сверьте состав.")
    pmk_tech_ids = fields.One2many(
        "pmk.metal.spec", "pmk_tech_source_id", "Технические расчёты",
        domain=[("pmk_kind", "=", "tech")])
    pmk_tech_count = fields.Integer("Технических", compute="_compute_pmk_tech_count")

    # Заявки на металл — только «Закупкам»: без прав на заказы поставщику
    # поле прочитать нельзя, и форма расчёта у менеджера упала бы.
    pmk_metal_request_ids = fields.One2many(
        "purchase.order", "pmk_tech_spec_id", "Заявки на металл",
        groups="purchase.group_purchase_user")
    pmk_metal_request_count = fields.Integer(
        "Заявки на металл", compute="_compute_pmk_metal_request_count",
        groups="purchase.group_purchase_user")

    # Сигналы технического расчёта — считаются при открытии, не хранятся.
    pmk_kp_compare_weight = fields.Char(
        "Металл в заявку: по КП → сейчас, т", compute="_compute_pmk_request_signals",
        help="Вес металла в заявку по расчёту КП и по техническому — одной "
             "мерой: листы целыми листами раскладки, прокат с использованием.")
    pmk_kp_compare_cost = fields.Char(
        "Металл в заявку: по КП → сейчас, ₽", compute="_compute_pmk_request_signals",
        help="Стоимость того же металла по ценам прайсов назначенных "
             "поставщиков. Позиции без цены — нулём, сказано рядом.")
    pmk_kp_compare_unpriced = fields.Boolean(
        "В заявке есть позиции без цены", compute="_compute_pmk_request_signals")
    pmk_tech_outdated_text = fields.Char(
        "Счёт изменился после копии", compute="_compute_pmk_request_signals",
        help="Счёт выставлен заново (новая редакция или из другого расчёта) "
             "после того, как сняли технический расчёт: сверьте состав. "
             "Ничего не блокирует.")
    pmk_request_warn_text = fields.Char(
        "Что в заявке не так", compute="_compute_pmk_request_signals",
        help="Листы без раскладки идут в заявку по весу (с запасом до целого "
             "листа); позиции без карточки товара и услуги в заявку не идут. "
             "Ничего не блокирует.")
    pmk_request_stale = fields.Boolean(
        "Состав изменился после заявки", compute="_compute_pmk_request_signals",
        help="Позиции или количества отличаются от черновиков заявки: нажмите "
             "«Заявка на металл» — черновики обновятся.")
    pmk_request_diff_text = fields.Char(
        "Расхождение с заявкой", compute="_compute_pmk_request_signals",
        help="Отправленную поставщику или подтверждённую заявку и количество, "
             "которое закупщик поправил в черновике, повторная «Заявка на "
             "металл» не трогает — расхождение видно здесь.")

    _pmk_one_tech_per_order = models.UniqueIndex(
        "(pmk_tech_order_id) WHERE pmk_kind = 'tech' AND pmk_tech_order_id IS NOT NULL",
        "К счёту покупателю уже есть технический расчёт — откройте его кнопкой "
        "«Технический расчёт».")

    # ─── Счётчики ──────────────────────────────────────────────────────
    @api.depends("pmk_tech_ids")
    def _compute_pmk_tech_count(self):
        for spec in self:
            spec.pmk_tech_count = len(spec.pmk_tech_ids)

    @api.depends("pmk_metal_request_ids.state")
    def _compute_pmk_metal_request_count(self):
        for spec in self:
            spec.pmk_metal_request_count = len(
                spec.pmk_metal_request_ids.filtered(lambda order: order.state != "cancel"))

    def copy_data(self, default=None):
        """«Дублировать» технический — технический (вид и расчёт КП с ним),
        без счёта: см. описание модуля."""
        vals_list = super().copy_data(default=default)
        default = default or {}
        for spec, vals in zip(self, vals_list):
            if spec.pmk_kind == "tech" and "pmk_kind" not in default:
                vals["pmk_kind"] = "tech"
                vals.setdefault("pmk_tech_source_id", spec.pmk_tech_source_id.id or False)
        return vals_list

    # ─── Технический не главный и не КП ─────────────────────────────────
    def _pmk_main_spec_candidates(self):
        return super()._pmk_main_spec_candidates().filtered(
            lambda spec: spec.pmk_kind != "tech")

    def _pmk_kp_move_stage(self, deal):
        """КП из технического расчёта не двигает сделку и не выставляет счёт:
        кнопки КП у него спрятаны, а счёт — по расчёту, который ушёл клиенту."""
        if any(spec.pmk_kind == "tech" for spec in self):
            return False
        return super()._pmk_kp_move_stage(deal)

    # ─── Заведение ──────────────────────────────────────────────────────
    @api.model
    def _pmk_tech_for_order(self, order):
        """Технический расчёт счёта: есть — он, нет — заводится копией."""
        order.ensure_one()
        if order.pmk_is_revision and order.pmk_revision_of_id:
            order = order.pmk_revision_of_id
        found = self.search(
            [("pmk_tech_order_id", "=", order.id), ("pmk_kind", "=", "tech")], limit=1)
        return found or self._pmk_create_tech(order)

    @api.model
    def _pmk_create_tech(self, order):
        source = order.pmk_spec_id
        deal = order.opportunity_id or source.opportunity_id
        partner = order.partner_id.commercial_partner_id or source.partner_id
        vals = {
            "pmk_kind": "tech",
            "pmk_tech_source_id": source.id or False,
            "pmk_tech_order_id": order.id,
            "pmk_tech_revision": order.pmk_revision or 1,
            "opportunity_id": deal.id or False,
            "partner_id": partner.id or False,
            "pmk_org_id": (order.pmk_org_id or source.pmk_org_id).id or False,
        }
        # Без чужих default_* (контекст формы счёта или планировщика).
        Spec = self.with_context(clean_context(self.env.context)).with_context(
            pmk_tech_copy=True, mail_create_nosubscribe=True)
        if source:
            tech = source.with_env(Spec.env).copy(vals)
            tech._pmk_tech_copy_layout(source)
        else:
            vals["note"] = source.note or deal.name or False
            tech = Spec.create(vals)
            tech._message_log(body=Markup(_(
                "Технический расчёт к %s. У счёта нет расчёта — состав набирается "
                "здесь.")) % order._get_html_link())
        order.sudo()._message_log(body=Markup(_(
            "Технический расчёт %(tech)s заведён: копия расчёта КП, по которому "
            "выставлен счёт. Расчёт КП не меняется.")) % {"tech": tech._get_html_link()})
        return tech.with_env(self.env)

    def _pmk_log_copy(self, origin):
        if not self.env.context.get("pmk_tech_copy"):
            return super()._pmk_log_copy(origin)
        self.ensure_one()
        on_date = self.price_date.strftime("%d.%m.%Y") if self.price_date else _("сегодня")
        body = Markup(_(
            "Технический расчёт к %(order)s: копия %(origin)s — изделия, состав, "
            "листовые детали и раскладка. Цены закупки — на %(date)s, из прайсов. "
            "Расчёт КП %(origin)s не меняется.")) % {
                "order": self.pmk_tech_order_id._get_html_link() if self.pmk_tech_order_id else "—",
                "origin": origin._get_html_link(),
                "date": on_date,
            }
        if self.no_price_count:
            body += Markup(" ") + _("Позиций без цены: %s.", self.no_price_count)
        self._message_log(body=body)
        return None

    def _pmk_tech_copy_layout(self, source):
        """Раскладка листов расчёта КП — в технический (пары деталей по
        порядку внутри изделий). Записываются только результаты раскладки:
        входы не меняются, и раскладка не гаснет (spec_layout.py)."""
        self.ensure_one()

        def ordered(records):
            return records.sorted(lambda rec: (rec.sequence, rec.id))

        old_products, new_products = ordered(source.product_ids), ordered(self.product_ids)
        if len(old_products) != len(new_products):
            return
        for old_product, new_product in zip(old_products, new_products):
            old_lines = ordered(old_product.line_sheet_ids)
            new_lines = ordered(new_product.line_sheet_ids)
            if len(old_lines) != len(new_lines):
                continue
            for old_line, new_line in zip(old_lines, new_lines):
                if old_line.layout_state == "none":
                    continue
                new_line.write({name: old_line[name] for name in LAYOUT_RESULTS})
        if source.layout_fingerprint:
            self.layout_fingerprint = source.layout_fingerprint

    # ─── Кнопки ─────────────────────────────────────────────────────────
    def action_pmk_open_tech(self):
        """Кнопка-счётчик «Технический» у расчёта КП."""
        self.ensure_one()
        techs = self.pmk_tech_ids
        action = {
            "type": "ir.actions.act_window",
            "name": _("Технические расчёты"),
            "res_model": "pmk.metal.spec",
            "target": "current",
        }
        if len(techs) == 1:
            action.update(name=techs.name, res_id=techs.id, views=[(False, "form")])
        else:
            action.update(views=[(False, "list"), (False, "form")],
                          domain=[("id", "in", techs.ids)])
        return action

    def action_pmk_metal_requests(self):
        self.ensure_one()
        return self.env["purchase.order"]._pmk_requests_window(
            [("pmk_tech_spec_id", "=", self.id)])

    # ─── Сигналы на форме ───────────────────────────────────────────────
    def _compute_pmk_request_signals(self):
        """Без @depends: считаются при открытии формы (и после сохранения).
        Заявки читаем от sudo — это только текст плашки; сами заявки видны
        по правам «Закупок»."""
        for spec in self:
            spec.pmk_kp_compare_weight = False
            spec.pmk_kp_compare_cost = False
            spec.pmk_kp_compare_unpriced = False
            spec.pmk_tech_outdated_text = False
            spec.pmk_request_warn_text = False
            spec.pmk_request_stale = False
            spec.pmk_request_diff_text = False
            if spec.pmk_kind != "tech" or not isinstance(spec.id, int):
                continue
            rows, notes = spec._pmk_metal_rows()
            spec._pmk_fill_compare(rows)
            spec.pmk_request_warn_text = spec._pmk_warn_text(notes) or False
            stale, diff = spec._pmk_request_drift(rows)
            spec.pmk_request_stale = stale
            spec.pmk_request_diff_text = diff or False
            spec.pmk_tech_outdated_text = spec._pmk_tech_outdated() or False

    def _pmk_fill_compare(self, rows):
        """Обе части — _pmk_metal_rows: по расчёту КП и по техническому (см.
        описание модуля). Не total_weight / total_cost_fact расчёта КП: там
        чистый вес деталей, а здесь целые листы — разница без правок."""
        self.ensure_one()
        kg = sum(row["kg"] for row in rows)
        cost = sum(row["cost"] for row in rows)
        unpriced = len([row for row in rows if not row["priced"]])
        source = self.pmk_tech_source_id
        # Тонны — без «т»: единица в подписи карточки, число короче (у
        # карточки nowrap, а в узкой правой колонке шапки «50,939 → 52,114 т»
        # упирался бы в рамку).
        if source:
            source_rows, _notes = source._pmk_metal_rows()
            self.pmk_kp_compare_weight = "%s → %s" % (
                _tons(sum(row["kg"] for row in source_rows)), _tons(kg))
            cost_text = "%s → %s" % (
                _rub(sum(row["cost"] for row in source_rows)), _rub(cost))
        else:
            self.pmk_kp_compare_weight = "— → %s" % _tons(kg)
            cost_text = "— → %s" % _rub(cost)
        if unpriced:
            cost_text += " · без цены %s поз." % unpriced
        self.pmk_kp_compare_cost = cost_text
        self.pmk_kp_compare_unpriced = bool(unpriced)

    def _pmk_tech_outdated(self):
        """Счёт изменился после копии? → текст плашки или "".

        Кнопка «Технический расчёт» есть и у выставленного счёта (решение 6
        по умолчанию): менеджер может поправить расчёт и снова отправить КП —
        у счёта новая редакция (тот же счёт), а то и другой расчёт. Копия
        этого не знает — говорим словами, ничего не блокируем."""
        self.ensure_one()
        order = self.pmk_tech_order_id.sudo()
        if not order or order.state == "cancel":
            return ""
        source = self.pmk_tech_source_id
        if order.pmk_spec_id and source and order.pmk_spec_id != source:
            return _(
                "Счёт %(order)s выставлен заново из расчёта %(spec)s (ред. %(rev)s), а "
                "технический снят с %(source)s — сверьте состав",
                order=order.name, spec=order.pmk_spec_id.name, rev=order.pmk_revision or 1,
                source=source.name)
        if self.pmk_tech_revision and (order.pmk_revision or 1) > self.pmk_tech_revision:
            return _(
                "Счёт %(order)s изменился после технического расчёта: ред. %(rev)s, копия "
                "снята с ред. %(old)s — сверьте состав с расчётом КП %(source)s",
                order=order.name, rev=order.pmk_revision, old=self.pmk_tech_revision,
                source=source.name or "—")
        return ""

    @api.model
    def _pmk_warn_text(self, notes):
        parts = []
        if notes["unlaid"]:
            parts.append(_("Листы без раскладки — в заявке по весу, до целого листа: %s",
                           ", ".join(notes["unlaid"])))
        if notes["no_card"]:
            parts.append(_("Нет карточки товара — в заявку не идут: %s",
                           ", ".join(notes["no_card"])))
        if notes["service"]:
            parts.append(_("Услуга, не металл — в заявку не идёт: %s",
                           ", ".join(notes["service"])))
        return "; ".join(parts)

    def _pmk_request_drift(self, rows):
        """(состав изменился после заявки?, текст расхождения с заявкой).

        «Изменился» — у инженера не то, что он заявил в прошлый раз
        (pmk_request_qty строки черновика), а не «не то, что в строке»:
        количество строки мог поправить закупщик, и плашка «нажмите «Заявка
        на металл»» звала бы перезаписать его правку. Расхождение — с
        отправленной / подтверждённой заявкой и с количеством, которое
        закупщик поправил в черновике (повтор его не трогает)."""
        self.ensure_one()
        orders = self.sudo().pmk_metal_request_ids.filtered(lambda order: order.state != "cancel")
        if not orders:
            return False, ""
        current = {row["key"]: row for row in rows}
        in_requests = set()
        stale = False
        diffs = []
        for order in orders.sorted("id"):
            for line in order.order_line.filtered("pmk_request_key"):
                key = line.pmk_request_key
                in_requests.add(key)
                row = current.get(key)
                if order.state == "draft":
                    requested = line._pmk_request_requested_qty()
                    if abs(requested - (row["qty"] if row else 0.0)) > EPS:
                        stale = True
                    if abs(line.product_qty - requested) <= EPS:
                        continue        # количество закупщик не правил
                if row and abs(line.product_qty - row["qty"]) <= EPS:
                    continue
                name = row["name"] if row else (line.product_id.display_name or line.name)
                mode = row["mode"] if row else key.split(":", 1)[0]
                engineer = self._pmk_qty_text(mode, row["qty"]) if row else _("нет")
                state = REQUEST_STATE_LABELS.get(order.state, order.state).lower()
                if order.state == "draft":
                    state = _("%s, количество правил закупщик", state)
                diffs.append(_(
                    "В заявке %(order)s (%(state)s): %(name)s — %(ordered)s, у инженера %(now)s",
                    order=order.name, state=state,
                    name=name, ordered=self._pmk_qty_text(mode, line.product_qty), now=engineer))
        if set(current) - in_requests:
            stale = True
        return stale, "; ".join(diffs)
